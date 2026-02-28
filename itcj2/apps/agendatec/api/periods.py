"""
Periods API v2 — CRUD de períodos académicos y días habilitados.
Fuente: itcj/apps/agendatec/routes/api/periods.py
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from itcj2.apps.agendatec.helpers import get_app_tz, parse_date_str, parse_datetime_str
from itcj2.apps.agendatec.schemas.periods import CreatePeriodBody, UpdatePeriodBody, SetEnabledDaysBody
from itcj2.dependencies import DbSession, require_perms, require_app, CurrentUser

from itcj.apps.agendatec.models.period_enabled_day import PeriodEnabledDay
from itcj.core.models.academic_period import AcademicPeriod
from itcj.core.services import period_service

router = APIRouter(tags=["agendatec-periods"])
logger = logging.getLogger(__name__)


# ==================== GET / ====================

@router.get("")
def list_periods(
    include_archived: bool = Query(False),
    status: Optional[str] = Query(None),
    order_by: str = Query("start_date"),
    order: str = Query("desc"),
    user: dict = require_perms("agendatec", ["agendatec.periods.api.read"]),
    db: DbSession = None,
):
    """Lista todos los períodos académicos con su configuración de AgendaTec."""
    query = db.query(AcademicPeriod).options(joinedload(AcademicPeriod.agendatec_config))

    if status:
        query = query.filter(AcademicPeriod.status == status)
    elif not include_archived:
        query = query.filter(AcademicPeriod.status != "ARCHIVED")

    if order_by == "start_date":
        query = query.order_by(
            AcademicPeriod.start_date.desc() if order == "desc" else AcademicPeriod.start_date.asc()
        )
    elif order_by == "name":
        query = query.order_by(
            AcademicPeriod.name.desc() if order == "desc" else AcademicPeriod.name.asc()
        )
    else:
        query = query.order_by(AcademicPeriod.start_date.desc())

    periods = query.all()

    items = []
    for p in periods:
        period_dict = p.to_dict()
        period_dict["agendatec_config"] = p.agendatec_config.to_dict() if p.agendatec_config else None
        period_dict["request_count"] = period_service.count_requests_in_period(p.id)
        items.append(period_dict)

    return {"items": items}


# ==================== POST / ====================

@router.post("", status_code=201)
def create_period(
    body: CreatePeriodBody,
    user: dict = require_perms("agendatec", ["agendatec.periods.api.create"]),
    db: DbSession = None,
):
    """Crea un nuevo período académico con su configuración de AgendaTec."""
    start_date = parse_date_str(body.start_date)
    end_date = parse_date_str(body.end_date)
    admission_start = parse_datetime_str(body.student_admission_start)
    admission_deadline = parse_datetime_str(body.student_admission_deadline)

    if not start_date or not end_date or not admission_start or not admission_deadline:
        raise HTTPException(status_code=400, detail="invalid_date_format")
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date_before_start_date")
    if admission_deadline < admission_start:
        raise HTTPException(status_code=400, detail="admission_deadline_before_start")

    if db.query(AcademicPeriod).filter_by(name=body.name).first():
        raise HTTPException(status_code=409, detail="period_name_already_exists")
    if db.query(AcademicPeriod).filter_by(code=body.code).first():
        raise HTTPException(status_code=409, detail="period_code_already_exists")

    uid = int(user["sub"])

    if body.status == "ACTIVE":
        db.query(AcademicPeriod).update({"status": "INACTIVE"})

    period = AcademicPeriod(
        code=body.code,
        name=body.name,
        start_date=start_date,
        end_date=end_date,
        status=body.status,
        created_by_id=uid,
    )
    db.add(period)
    db.flush()

    try:
        period_service.create_agendatec_config(
            period_id=period.id,
            student_admission_start=admission_start,
            student_admission_deadline=admission_deadline,
            max_cancellations=body.max_cancellations_per_student,
            allow_drop=body.allow_drop_requests,
            allow_appointment=body.allow_appointment_requests,
            created_by_id=uid,
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail={"error": "failed_to_create_config", "message": str(e)})

    db.commit()

    result = period.to_dict()
    config = period_service.get_agendatec_config(period.id)
    if config:
        result["agendatec_config"] = config.to_dict()
    return result


# ==================== GET /<period_id> ====================

@router.get("/{period_id}")
def get_period(
    period_id: int,
    user: dict = require_perms("agendatec", ["agendatec.periods.api.read"]),
    db: DbSession = None,
):
    """Obtiene un período específico por ID con su configuración."""
    period = (
        db.query(AcademicPeriod)
        .options(joinedload(AcademicPeriod.agendatec_config))
        .filter_by(id=period_id)
        .first()
    )
    if not period:
        raise HTTPException(status_code=404, detail="period_not_found")

    result = period.to_dict()
    result["agendatec_config"] = period.agendatec_config.to_dict() if period.agendatec_config else None
    return result


# ==================== PATCH /<period_id> ====================

@router.patch("/{period_id}")
def update_period(
    period_id: int,
    body: UpdatePeriodBody,
    user: dict = require_perms("agendatec", ["agendatec.periods.api.update"]),
    db: DbSession = None,
):
    """Actualiza un período académico y su configuración de AgendaTec."""
    period = db.query(AcademicPeriod).filter_by(id=period_id).first()
    if not period:
        raise HTTPException(status_code=404, detail="period_not_found")

    if body.code is not None:
        existing = db.query(AcademicPeriod).filter(
            AcademicPeriod.code == body.code, AcademicPeriod.id != period_id
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="period_code_already_exists")
        period.code = body.code

    if body.name is not None:
        existing = db.query(AcademicPeriod).filter(
            AcademicPeriod.name == body.name, AcademicPeriod.id != period_id
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="period_name_already_exists")
        period.name = body.name

    if body.start_date is not None:
        sd = parse_date_str(body.start_date)
        if not sd:
            raise HTTPException(status_code=400, detail="invalid_start_date_format")
        period.start_date = sd

    if body.end_date is not None:
        ed = parse_date_str(body.end_date)
        if not ed:
            raise HTTPException(status_code=400, detail="invalid_end_date_format")
        period.end_date = ed

    if period.end_date < period.start_date:
        raise HTTPException(status_code=400, detail="end_date_before_start_date")

    if body.status is not None:
        if body.status == "ACTIVE":
            db.query(AcademicPeriod).filter(AcademicPeriod.id != period_id).update({"status": "INACTIVE"})
        period.status = body.status

    period.updated_at = datetime.now(get_app_tz())

    # Actualizar configuración de AgendaTec
    config_fields = {}
    if body.student_admission_start is not None:
        dt = parse_datetime_str(body.student_admission_start)
        if not dt:
            raise HTTPException(status_code=400, detail="invalid_admission_start_format")
        config_fields["student_admission_start"] = dt

    if body.student_admission_deadline is not None:
        dt = parse_datetime_str(body.student_admission_deadline)
        if not dt:
            raise HTTPException(status_code=400, detail="invalid_deadline_format")
        config_fields["student_admission_deadline"] = dt

    if (
        "student_admission_start" in config_fields
        and "student_admission_deadline" in config_fields
        and config_fields["student_admission_deadline"] < config_fields["student_admission_start"]
    ):
        raise HTTPException(status_code=400, detail="admission_deadline_before_start")

    if body.max_cancellations_per_student is not None:
        config_fields["max_cancellations_per_student"] = body.max_cancellations_per_student
    if body.allow_drop_requests is not None:
        config_fields["allow_drop_requests"] = body.allow_drop_requests
    if body.allow_appointment_requests is not None:
        config_fields["allow_appointment_requests"] = body.allow_appointment_requests

    if config_fields:
        try:
            period_service.update_agendatec_config(period_id, **config_fields)
        except ValueError as e:
            raise HTTPException(status_code=404, detail={"error": "config_not_found", "message": str(e)})

    db.commit()

    result = period.to_dict()
    config = period_service.get_agendatec_config(period.id)
    if config:
        result["agendatec_config"] = config.to_dict()
    return result


# ==================== POST /<period_id>/activate ====================

@router.post("/{period_id}/activate")
def activate_period(
    period_id: int,
    user: dict = require_perms("agendatec", ["agendatec.periods.api.activate"]),
    db: DbSession = None,
):
    """Activa un período y desactiva todos los demás."""
    uid = int(user["sub"])
    try:
        period = period_service.activate_period(period_id, uid)
        return period.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail={"error": "period_not_found", "message": str(e)})


# ==================== DELETE /<period_id> ====================

@router.delete("/{period_id}", status_code=204)
def delete_period(
    period_id: int,
    user: dict = require_perms("agendatec", ["agendatec.periods.api.delete"]),
    db: DbSession = None,
):
    """Elimina un período. Solo si no tiene solicitudes vinculadas."""
    period = db.query(AcademicPeriod).filter_by(id=period_id).first()
    if not period:
        raise HTTPException(status_code=404, detail="period_not_found")

    request_count = period_service.count_requests_in_period(period_id)
    if request_count > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "period_has_requests",
                "message": f"El período tiene {request_count} solicitud(es). Use ARCHIVED en su lugar.",
                "request_count": request_count,
            },
        )

    db.delete(period)
    db.commit()


# ==================== GET /<period_id>/enabled-days ====================

@router.get("/{period_id}/enabled-days")
def get_enabled_days(
    period_id: int,
    user: dict = require_perms("agendatec", ["agendatec.periods.api.read"]),
    db: DbSession = None,
):
    """Obtiene los días habilitados de un período."""
    period = db.query(AcademicPeriod).filter_by(id=period_id).first()
    if not period:
        raise HTTPException(status_code=404, detail="period_not_found")

    enabled_days = (
        db.query(PeriodEnabledDay)
        .filter_by(period_id=period_id)
        .order_by(PeriodEnabledDay.day)
        .all()
    )
    return {"days": [ed.to_dict() for ed in enabled_days]}


# ==================== POST /<period_id>/enabled-days ====================

@router.post("/{period_id}/enabled-days")
def set_enabled_days(
    period_id: int,
    body: SetEnabledDaysBody,
    user: dict = require_perms("agendatec", ["agendatec.periods.api.update"]),
    db: DbSession = None,
):
    """Configura los días habilitados para un período (reemplaza los existentes)."""
    period = db.query(AcademicPeriod).filter_by(id=period_id).first()
    if not period:
        raise HTTPException(status_code=404, detail="period_not_found")

    days = []
    for day_str in body.days:
        d = parse_date_str(day_str)
        if not d:
            raise HTTPException(
                status_code=400, detail={"error": "invalid_date_format", "invalid_date": day_str}
            )
        if not (period.start_date <= d <= period.end_date):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "day_out_of_period_range",
                    "day": d.isoformat(),
                    "period_range": {
                        "start": period.start_date.isoformat(),
                        "end": period.end_date.isoformat(),
                    },
                },
            )
        days.append(d)

    db.query(PeriodEnabledDay).filter_by(period_id=period_id).delete()

    uid = int(user["sub"])
    for d in days:
        db.add(PeriodEnabledDay(period_id=period_id, day=d, created_by_id=uid))

    db.commit()
    return {
        "ok": True,
        "message": "enabled_days_updated",
        "enabled_days_count": len(days),
        "days": [d.isoformat() for d in days],
    }


# ==================== DELETE /<period_id>/enabled-days/<day_id> ====================

@router.delete("/{period_id}/enabled-days/{day_id}", status_code=204)
def delete_enabled_day(
    period_id: int,
    day_id: int,
    user: dict = require_perms("agendatec", ["agendatec.periods.api.update"]),
    db: DbSession = None,
):
    """Elimina un día habilitado específico."""
    enabled_day = db.query(PeriodEnabledDay).filter_by(id=day_id, period_id=period_id).first()
    if not enabled_day:
        raise HTTPException(status_code=404, detail="enabled_day_not_found")

    db.delete(enabled_day)
    db.commit()


# ==================== GET /active ====================

@router.get("/active/info")
def get_active_period(
    user: dict = require_app("agendatec"),
    db: DbSession = None,
):
    """
    Obtiene el período activo con días habilitados y configuración.
    Requiere autenticación con acceso a agendatec.
    """
    period = period_service.get_active_period()
    if not period:
        raise HTTPException(status_code=404, detail="no_active_period")

    enabled_days = period_service.get_enabled_days(period.id)
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

    return result


# ==================== GET /<period_id>/stats ====================

@router.get("/{period_id}/stats")
def get_period_stats(
    period_id: int,
    user: dict = require_perms("agendatec", ["agendatec.periods.api.read"]),
    db: DbSession = None,
):
    """Obtiene estadísticas de un período académico."""
    from itcj.apps.agendatec.models.request import Request

    period = db.query(AcademicPeriod).filter_by(id=period_id).first()
    if not period:
        raise HTTPException(status_code=404, detail="period_not_found")

    stats = (
        db.query(Request.type, Request.status, func.count(Request.id).label("count"))
        .filter_by(period_id=period_id)
        .group_by(Request.type, Request.status)
        .all()
    )

    enabled_days_objs = period_service.get_enabled_days(period_id)

    stats_dict = {
        "period": period.to_dict(),
        "total_requests": period_service.count_requests_in_period(period_id),
        "by_type": {},
        "by_status": {},
        "enabled_days_count": len(enabled_days_objs),
        "enabled_days": [d.isoformat() for d in enabled_days_objs],
    }

    for req_type, status, count in stats:
        stats_dict["by_type"][req_type] = stats_dict["by_type"].get(req_type, 0) + count
        stats_dict["by_status"][status] = stats_dict["by_status"].get(status, 0) + count

    stats_dict["pending_requests"] = stats_dict["by_status"].get("PENDING", 0)
    stats_dict["resolved_requests"] = (
        stats_dict["by_status"].get("APPROVED", 0)
        + stats_dict["by_status"].get("REJECTED", 0)
        + stats_dict["by_status"].get("COMPLETED", 0)
    )

    return stats_dict
