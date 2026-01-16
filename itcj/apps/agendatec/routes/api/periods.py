# itcj/apps/agendatec/routes/api/periods.py
"""
API endpoints para gestión de períodos académicos.

Este módulo proporciona endpoints CRUD completos para:
- Gestión de períodos académicos (crear, listar, actualizar, activar)
- Configuración de días habilitados por período
- Consulta del período activo (endpoint público para estudiantes)
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func

from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.period_enabled_day import PeriodEnabledDay
from itcj.core.models.academic_period import AcademicPeriod
from itcj.core.models.user import User
from itcj.core.services import period_service
from itcj.core.utils.decorators import api_app_required

api_periods_bp = Blueprint("api_periods", __name__)


# ==================== HELPERS ====================

def _get_tz() -> ZoneInfo:
    """Timezone de la aplicación"""
    return ZoneInfo("America/Ciudad_Juarez")


def _parse_date(date_str: str) -> Optional[date]:
    """
    Parsea una fecha en formato ISO (YYYY-MM-DD).

    Returns:
        date o None si hay error
    """
    try:
        return datetime.fromisoformat(date_str).date()
    except (ValueError, AttributeError):
        return None


def _parse_datetime(dt_str: str) -> Optional[datetime]:
    """
    Parsea un datetime en formato ISO.
    Asegura que tenga timezone.

    Returns:
        datetime con timezone o None si hay error
    """
    try:
        dt = datetime.fromisoformat(dt_str)
        # Si no tiene timezone, agregar el de la app
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_get_tz())
        return dt
    except (ValueError, AttributeError):
        return None


def _get_current_user_id() -> Optional[int]:
    """Obtiene el ID del usuario actual"""
    cu = g.get("current_user")
    if not cu:
        return None
    return int(cu.get("sub"))


# ==================== ENDPOINTS: PERÍODOS ====================

@api_periods_bp.route("", methods=["GET"])
@api_app_required("agendatec", perms=["agendatec.periods.api.read"])
def list_periods():
    """
    Lista todos los períodos académicos con su configuración de AgendaTec.

    Query params:
        - include_archived: bool (default=false) - Incluir períodos archivados
        - status: str (opcional) - Filtrar por estado (ACTIVE, INACTIVE, ARCHIVED)
        - order_by: str (default=start_date) - Campo de ordenamiento
        - order: str (default=desc) - Dirección (asc/desc)

    Returns:
        200: Lista de períodos con configuración de AgendaTec
    """
    from sqlalchemy.orm import joinedload

    include_archived = request.args.get("include_archived", "false").lower() == "true"
    status_filter = request.args.get("status")

    query = db.session.query(AcademicPeriod).options(
        joinedload(AcademicPeriod.agendatec_config)
    )

    # Filtro por estado específico
    if status_filter:
        query = query.filter(AcademicPeriod.status == status_filter)
    elif not include_archived:
        query = query.filter(AcademicPeriod.status != "ARCHIVED")

    # Ordenamiento
    order_by = request.args.get("order_by", "start_date")
    order = request.args.get("order", "desc")

    if order_by == "start_date":
        query = query.order_by(
            AcademicPeriod.start_date.desc() if order == "desc"
            else AcademicPeriod.start_date.asc()
        )
    elif order_by == "name":
        query = query.order_by(
            AcademicPeriod.name.desc() if order == "desc"
            else AcademicPeriod.name.asc()
        )
    else:
        # Default
        query = query.order_by(AcademicPeriod.start_date.desc())

    periods = query.all()

    # Construir respuesta con agendatec_config incluido
    items = []
    for p in periods:
        period_dict = p.to_dict()
        # Incluir configuración de AgendaTec
        if p.agendatec_config:
            period_dict["agendatec_config"] = p.agendatec_config.to_dict()
        else:
            period_dict["agendatec_config"] = None
        # Incluir conteo de solicitudes
        period_dict["request_count"] = period_service.count_requests_in_period(p.id)
        items.append(period_dict)

    return jsonify({"items": items}), 200


@api_periods_bp.route("", methods=["POST"])
@api_app_required("agendatec", perms=["agendatec.periods.api.create"])
def create_period():
    """
    Crea un nuevo período académico con su configuración de AgendaTec.

    Body (JSON):
        - name: str (requerido) - Nombre del período
        - start_date: str (requerido) - Fecha inicio (YYYY-MM-DD)
        - end_date: str (requerido) - Fecha fin (YYYY-MM-DD)
        - student_admission_deadline: str (requerido) - Fecha/hora límite ISO
        - status: str (opcional) - ACTIVE/INACTIVE/ARCHIVED (default: INACTIVE)
        - max_cancellations_per_student: int (opcional) - Límite de cancelaciones (default: 2)
        - allow_drop_requests: bool (opcional) - Permitir bajas (default: true)
        - allow_appointment_requests: bool (opcional) - Permitir citas (default: true)

    Returns:
        201: Período creado con su configuración
        400: Datos inválidos
    """
    data = request.json

    # Validar campos requeridos
    required = ["code", "name", "start_date", "end_date", "student_admission_start", "student_admission_deadline"]
    if not all(k in data for k in required):
        return jsonify({"error": "missing_fields", "required": required}), 400

    # Parsear fechas
    start_date = _parse_date(data["start_date"])
    end_date = _parse_date(data["end_date"])
    admission_start = _parse_datetime(data["student_admission_start"])
    admission_deadline = _parse_datetime(data["student_admission_deadline"])

    if not start_date or not end_date or not admission_start or not admission_deadline:
        return jsonify({"error": "invalid_date_format"}), 400

    # Validar rango de fechas del período
    if end_date < start_date:
        return jsonify({"error": "end_date_before_start_date"}), 400

    # Validar rango de ventana de admisión
    if admission_deadline < admission_start:
        return jsonify({"error": "admission_deadline_before_start", "message": "La fecha límite de admisión debe ser posterior al inicio"}), 400

    # Validar que el nombre no exista
    existing = db.session.query(AcademicPeriod).filter_by(name=data["name"]).first()
    if existing:
        return jsonify({"error": "period_name_already_exists"}), 409

    # Validar que el código no exista
    existing_code = db.session.query(AcademicPeriod).filter_by(code=data["code"]).first()
    if existing_code:
        return jsonify({"error": "period_code_already_exists"}), 409

    current_user_id = _get_current_user_id()

    # Crear período
    period = AcademicPeriod(
        code=data["code"],
        name=data["name"],
        start_date=start_date,
        end_date=end_date,
        status=data.get("status", "INACTIVE"),
        created_by_id=current_user_id
    )

    # Si se marca como ACTIVE, desactivar los demás
    if period.status == "ACTIVE":
        db.session.query(AcademicPeriod).update({"status": "INACTIVE"})

    db.session.add(period)
    db.session.flush()  # Para obtener el ID del período

    # Crear configuración de AgendaTec automáticamente
    try:
        period_service.create_agendatec_config(
            period_id=period.id,
            student_admission_start=admission_start,
            student_admission_deadline=admission_deadline,
            max_cancellations=data.get("max_cancellations_per_student", 2),
            allow_drop=data.get("allow_drop_requests", True),
            allow_appointment=data.get("allow_appointment_requests", True),
            created_by_id=current_user_id
        )
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": "failed_to_create_config", "message": str(e)}), 500

    db.session.commit()

    # Incluir configuración en la respuesta
    result = period.to_dict()
    config = period_service.get_agendatec_config(period.id)
    if config:
        result["agendatec_config"] = config.to_dict()

    return jsonify(result), 201


@api_periods_bp.route("/<int:period_id>", methods=["GET"])
@api_app_required("agendatec", perms=["agendatec.periods.api.read"])
def get_period(period_id: int):
    """
    Obtiene un período específico por ID con su configuración de AgendaTec.

    Returns:
        200: Datos del período con configuración
        404: Período no encontrado
    """
    from sqlalchemy.orm import joinedload

    period = db.session.query(AcademicPeriod).options(
        joinedload(AcademicPeriod.agendatec_config)
    ).filter_by(id=period_id).first()

    if not period:
        return jsonify({"error": "period_not_found"}), 404

    result = period.to_dict()
    # Incluir configuración de AgendaTec
    if period.agendatec_config:
        result["agendatec_config"] = period.agendatec_config.to_dict()

    return jsonify(result), 200


@api_periods_bp.route("/<int:period_id>", methods=["PATCH"])
@api_app_required("agendatec", perms=["agendatec.periods.api.update"])
def update_period(period_id: int):
    """
    Actualiza un período académico y su configuración de AgendaTec.

    Body (JSON) - todos los campos son opcionales:
        - name: str
        - start_date: str (YYYY-MM-DD)
        - end_date: str (YYYY-MM-DD)
        - student_admission_deadline: str (ISO datetime)
        - max_cancellations_per_student: int
        - allow_drop_requests: bool
        - allow_appointment_requests: bool
        - status: str (ACTIVE/INACTIVE/ARCHIVED)

    Returns:
        200: Período actualizado
        400: Datos inválidos
        404: Período no encontrado
    """
    period = db.session.query(AcademicPeriod).filter_by(id=period_id).first()

    if not period:
        return jsonify({"error": "period_not_found"}), 404

    data = request.json

    # Actualizar campos del período
    if "code" in data:
        # Validar que el código no exista en otro período
        existing = db.session.query(AcademicPeriod).filter(
            AcademicPeriod.code == data["code"],
            AcademicPeriod.id != period_id
        ).first()
        if existing:
            return jsonify({"error": "period_code_already_exists"}), 409
        period.code = data["code"]

    if "name" in data:
        # Validar que el nombre no exista en otro período
        existing = db.session.query(AcademicPeriod).filter(
            AcademicPeriod.name == data["name"],
            AcademicPeriod.id != period_id
        ).first()
        if existing:
            return jsonify({"error": "period_name_already_exists"}), 409
        period.name = data["name"]

    if "start_date" in data:
        start_date = _parse_date(data["start_date"])
        if not start_date:
            return jsonify({"error": "invalid_start_date_format"}), 400
        period.start_date = start_date

    if "end_date" in data:
        end_date = _parse_date(data["end_date"])
        if not end_date:
            return jsonify({"error": "invalid_end_date_format"}), 400
        period.end_date = end_date

    # Validar rango de fechas
    if period.end_date < period.start_date:
        return jsonify({"error": "end_date_before_start_date"}), 400

    # Si se cambia status a ACTIVE, desactivar los demás
    if "status" in data:
        if data["status"] == "ACTIVE":
            db.session.query(AcademicPeriod).filter(
                AcademicPeriod.id != period_id
            ).update({"status": "INACTIVE"})
        period.status = data["status"]

    period.updated_at = datetime.now(_get_tz())

    # Actualizar configuración de AgendaTec si se proporcionan campos
    config_fields = {}
    if "student_admission_start" in data:
        admission_start = _parse_datetime(data["student_admission_start"])
        if not admission_start:
            return jsonify({"error": "invalid_admission_start_format"}), 400
        config_fields["student_admission_start"] = admission_start

    if "student_admission_deadline" in data:
        deadline = _parse_datetime(data["student_admission_deadline"])
        if not deadline:
            return jsonify({"error": "invalid_deadline_format"}), 400
        config_fields["student_admission_deadline"] = deadline

    # Validar que el deadline sea posterior al start si ambos se proporcionan
    if "student_admission_start" in config_fields and "student_admission_deadline" in config_fields:
        if config_fields["student_admission_deadline"] < config_fields["student_admission_start"]:
            return jsonify({"error": "admission_deadline_before_start"}), 400

    if "max_cancellations_per_student" in data:
        config_fields["max_cancellations_per_student"] = data["max_cancellations_per_student"]

    if "allow_drop_requests" in data:
        config_fields["allow_drop_requests"] = data["allow_drop_requests"]

    if "allow_appointment_requests" in data:
        config_fields["allow_appointment_requests"] = data["allow_appointment_requests"]

    # Actualizar configuración si hay campos
    if config_fields:
        try:
            period_service.update_agendatec_config(period_id, **config_fields)
        except ValueError as e:
            return jsonify({"error": "config_not_found", "message": str(e)}), 404

    db.session.commit()

    # Incluir configuración en la respuesta
    result = period.to_dict()
    config = period_service.get_agendatec_config(period.id)
    if config:
        result["agendatec_config"] = config.to_dict()

    return jsonify(result), 200


@api_periods_bp.route("/<int:period_id>/activate", methods=["POST"])
@api_app_required("agendatec", perms=["agendatec.periods.api.activate"])
def activate_period(period_id: int):
    """
    Activa un período y desactiva todos los demás.

    IMPORTANTE: Solo un período puede estar activo a la vez.

    Returns:
        200: Período activado
        404: Período no encontrado
    """
    try:
        period = period_service.activate_period(period_id, _get_current_user_id())
        return jsonify(period.to_dict()), 200
    except ValueError as e:
        return jsonify({"error": "period_not_found", "message": str(e)}), 404


@api_periods_bp.route("/<int:period_id>", methods=["DELETE"])
@api_app_required("agendatec", perms=["agendatec.periods.api.delete"])
def delete_period(period_id: int):
    """
    Elimina un período académico.

    NOTA: Solo se puede eliminar si no tiene solicitudes vinculadas.
    Para períodos con solicitudes, usar PATCH para cambiar status a ARCHIVED.

    Returns:
        204: Período eliminado
        404: Período no encontrado
        409: Período tiene solicitudes vinculadas
    """
    period = db.session.query(AcademicPeriod).filter_by(id=period_id).first()

    if not period:
        return jsonify({"error": "period_not_found"}), 404

    # Verificar si tiene solicitudes
    request_count = period_service.count_requests_in_period(period_id)
    if request_count > 0:
        return jsonify({
            "error": "period_has_requests",
            "message": f"El período tiene {request_count} solicitud(es) vinculada(s). Use ARCHIVED en su lugar.",
            "request_count": request_count
        }), 409

    db.session.delete(period)
    db.session.commit()

    return "", 204


# ==================== ENDPOINTS: DÍAS HABILITADOS ====================

@api_periods_bp.route("/<int:period_id>/enabled-days", methods=["GET"])
@api_app_required("agendatec", perms=["agendatec.periods.api.read"])
def get_enabled_days(period_id: int):
    """
    Obtiene los días habilitados de un período.

    Returns:
        200: Lista de días habilitados
        404: Período no encontrado
    """
    period = db.session.query(AcademicPeriod).filter_by(id=period_id).first()
    if not period:
        return jsonify({"error": "period_not_found"}), 404

    enabled_days = db.session.query(PeriodEnabledDay).filter_by(
        period_id=period_id
    ).order_by(PeriodEnabledDay.day).all()

    return jsonify({"days": [ed.to_dict() for ed in enabled_days]}), 200


@api_periods_bp.route("/<int:period_id>/enabled-days", methods=["POST"])
@api_app_required("agendatec", perms=["agendatec.periods.api.update"])
def set_enabled_days(period_id: int):
    """
    Configura los días habilitados para un período.

    IMPORTANTE: Reemplaza completamente los días existentes.

    Body (JSON):
        - days: list[str] (requerido) - Lista de fechas en formato YYYY-MM-DD

    Ejemplo:
        {"days": ["2025-08-25", "2025-08-26", "2025-08-27"]}

    Returns:
        200: Días configurados exitosamente
        400: Datos inválidos
        404: Período no encontrado
    """
    period = db.session.query(AcademicPeriod).filter_by(id=period_id).first()
    if not period:
        return jsonify({"error": "period_not_found"}), 404

    data = request.json

    if "days" not in data or not isinstance(data["days"], list):
        return jsonify({"error": "invalid_payload", "message": "Se requiere 'days' como lista"}), 400

    # Parsear días
    days = []
    for day_str in data["days"]:
        day = _parse_date(day_str)
        if not day:
            return jsonify({"error": "invalid_date_format", "invalid_date": day_str}), 400
        days.append(day)

    # Validar que los días estén dentro del rango del período
    for day in days:
        if not (period.start_date <= day <= period.end_date):
            return jsonify({
                "error": "day_out_of_period_range",
                "day": day.isoformat(),
                "period_range": {
                    "start": period.start_date.isoformat(),
                    "end": period.end_date.isoformat()
                }
            }), 400

    # Eliminar días existentes
    db.session.query(PeriodEnabledDay).filter_by(period_id=period_id).delete()

    # Insertar nuevos días
    current_user_id = _get_current_user_id()
    for day in days:
        enabled_day = PeriodEnabledDay(
            period_id=period_id,
            day=day,
            created_by_id=current_user_id
        )
        db.session.add(enabled_day)

    db.session.commit()

    return jsonify({
        "ok": True,
        "message": "enabled_days_updated",
        "enabled_days_count": len(days),
        "days": [d.isoformat() for d in days]
    }), 200


@api_periods_bp.route("/<int:period_id>/enabled-days/<int:day_id>", methods=["DELETE"])
@api_app_required("agendatec", perms=["agendatec.periods.api.update"])
def delete_enabled_day(period_id: int, day_id: int):
    """
    Elimina un día habilitado específico.

    Returns:
        204: Día eliminado
        404: Día no encontrado
    """
    enabled_day = db.session.query(PeriodEnabledDay).filter_by(
        id=day_id,
        period_id=period_id
    ).first()

    if not enabled_day:
        return jsonify({"error": "enabled_day_not_found"}), 404

    db.session.delete(enabled_day)
    db.session.commit()

    return "", 204


# ==================== ENDPOINT PÚBLICO: PERÍODO ACTIVO ====================

@api_periods_bp.route("/active", methods=["GET"])
def get_active_period():
    """
    Obtiene el período activo actual (endpoint público).

    Este endpoint NO requiere autenticación y es usado por estudiantes
    para obtener información del período activo y los días habilitados.

    Returns:
        200: Datos del período activo con días habilitados y configuración
        404: No hay período activo
    """
    period = period_service.get_active_period()

    if not period:
        return jsonify({"error": "no_active_period"}), 404

    # Incluir días habilitados
    enabled_days = period_service.get_enabled_days(period.id)

    # Incluir configuración de AgendaTec
    config = period_service.get_agendatec_config(period.id)

    result = period.to_dict()
    result["enabled_days"] = [d.isoformat() for d in enabled_days]

    if config:
        result["agendatec_config"] = config.to_dict()
        result["is_window_open"] = config.is_student_window_open()
        result["window_status"] = config.get_window_status()
    else:
        result["is_window_open"] = False
        result["window_status"] = {"is_open": False, "reason": "no_config"}

    return jsonify(result), 200


# ==================== ENDPOINT DE ESTADÍSTICAS ====================

@api_periods_bp.route("/<int:period_id>/stats", methods=["GET"])
@api_app_required("agendatec", perms=["agendatec.periods.api.read"])
def get_period_stats(period_id: int):
    """
    Obtiene estadísticas de un período académico.

    Returns:
        200: Estadísticas del período
        404: Período no encontrado
    """
    period = db.session.query(AcademicPeriod).filter_by(id=period_id).first()
    if not period:
        return jsonify({"error": "period_not_found"}), 404

    from itcj.apps.agendatec.models.request import Request

    # Contar solicitudes por tipo
    stats = db.session.query(
        Request.type,
        Request.status,
        func.count(Request.id).label("count")
    ).filter_by(period_id=period_id).group_by(
        Request.type, Request.status
    ).all()

    # Obtener días habilitados
    enabled_days_objs = period_service.get_enabled_days(period_id)
    enabled_days_list = [d.isoformat() for d in enabled_days_objs]

    # Organizar estadísticas
    stats_dict = {
        "period": period.to_dict(),
        "total_requests": period_service.count_requests_in_period(period_id),
        "by_type": {},
        "by_status": {},
        "enabled_days_count": len(enabled_days_objs),
        "enabled_days": enabled_days_list
    }

    for req_type, status, count in stats:
        # Por tipo
        if req_type not in stats_dict["by_type"]:
            stats_dict["by_type"][req_type] = 0
        stats_dict["by_type"][req_type] += count

        # Por estado
        if status not in stats_dict["by_status"]:
            stats_dict["by_status"][status] = 0
        stats_dict["by_status"][status] += count

    # Agregar campos calculados para el frontend
    stats_dict["pending_requests"] = stats_dict["by_status"].get("PENDING", 0)
    stats_dict["resolved_requests"] = (
        stats_dict["by_status"].get("APPROVED", 0) +
        stats_dict["by_status"].get("REJECTED", 0) +
        stats_dict["by_status"].get("COMPLETED", 0)
    )

    return jsonify(stats_dict), 200
