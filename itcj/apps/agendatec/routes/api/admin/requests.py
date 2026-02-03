# routes/api/admin/requests.py
"""
Endpoints para gestión de solicitudes de administración.

Incluye:
- admin_list_requests: Listado de solicitudes con filtros
- admin_change_request_status: Cambio de estado de solicitud
- admin_create_request: Crear solicitud como admin
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.appointment import Appointment
from itcj.apps.agendatec.models.request import Request as Req
from itcj.apps.agendatec.models.time_slot import TimeSlot
from itcj.core.models.coordinator import Coordinator
from itcj.core.models.program import Program
from itcj.core.models.program_coordinator import ProgramCoordinator
from itcj.core.models.user import User
from itcj.core.services import period_service
from itcj.core.sockets.notifications import push_notification
from itcj.core.sockets.requests import broadcast_appointment_created, broadcast_drop_created
from itcj.core.utils.decorators import api_app_required, api_auth_required
from itcj.core.utils.notify import create_notification
from itcj.core.utils.redis_conn import get_redis

from .helpers import paginate, range_from_query

admin_requests_bp = Blueprint("admin_requests", __name__)


@admin_requests_bp.get("/requests")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.requests.api.read.all"])
def admin_list_requests():
    """
    Lista solicitudes con filtros y paginación.

    Query params:
        from, to: Rango de fechas
        status: Filtro por estado
        program_id: Filtro por programa
        coordinator_id: Filtro por coordinador
        period_id: Filtro por período
        q: Búsqueda por nombre/control del alumno
        limit, offset: Paginación

    Returns:
        JSON con items y total
    """
    start, end = range_from_query()
    status = request.args.get("status")
    program_id = request.args.get("program_id", type=int)
    coordinator_id = request.args.get("coordinator_id", type=int)
    period_id = request.args.get("period_id", type=int)
    q = request.args.get("q", "").strip()

    qry = (
        db.session.query(Req)
        .options(
            joinedload(Req.appointment).joinedload(Appointment.coordinator).joinedload(Coordinator.user),
            joinedload(Req.program).joinedload(Program.program_coordinators).joinedload(ProgramCoordinator.coordinator).joinedload(Coordinator.user),
            joinedload(Req.student),
        )
        .filter(Req.created_at >= start, Req.created_at <= end)
    )
    if status:
        qry = qry.filter(Req.status == status)
    if program_id:
        qry = qry.filter(Req.program_id == program_id)
    if coordinator_id:
        qry = qry.join(Appointment, Appointment.request_id == Req.id).filter(
            Appointment.coordinator_id == coordinator_id
        )
    if period_id:
        qry = qry.filter(Req.period_id == period_id)
    if q:
        qry = qry.join(User, User.id == Req.student_id).filter(
            or_(User.control_number.ilike(f"%{q}%"), User.username.ilike(f"%{q}%"), User.full_name.ilike(f"%{q}%"))
        )

    items, total = paginate(qry.order_by(Req.created_at.desc()))

    def _to_dict(r: Req):
        a: Optional[Appointment] = r.appointment
        coord_name = None
        coord_id = None

        if a and a.coordinator and a.coordinator.user:
            coord_name = a.coordinator.user.full_name
            coord_id = a.coordinator_id
        elif r.program and r.program.program_coordinators:
            first_coord = r.program.program_coordinators[0] if r.program.program_coordinators else None
            if first_coord and first_coord.coordinator and first_coord.coordinator.user:
                coord_name = first_coord.coordinator.user.full_name
                coord_id = first_coord.coordinator.id

        return {
            "id": r.id,
            "type": r.type,
            "status": r.status,
            "program": r.program.name if r.program else None,
            "student": r.student.full_name if r.student else None,
            "student_control_number": r.student.control_number if r.student.control_number else r.student.username,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "coordinator_name": coord_name,
            "coordinator_id": coord_id,
            "appointment": {
                "id": a.id,
                "status": a.status,
                "coordinator_id": a.coordinator_id,
                "coordinator_name": coord_name if a else None,
                "time_slot_id": a.slot_id,
            } if a else None,
        }

    return jsonify({"items": [_to_dict(x) for x in items], "total": total})


@admin_requests_bp.patch("/requests/<int:req_id>/status")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.requests.api.update.all"])
def admin_change_request_status(req_id: int):
    """
    Cambia el estado de una solicitud.

    Body JSON:
        status: Nuevo estado
        reason: Razón del cambio (opcional)

    Returns:
        JSON con resultado de la operación
    """
    from itcj.apps.agendatec.services.request_ops import admin_change_request_status as change_status

    data = request.get_json(silent=True) or {}
    new_status: str = data.get("status")
    reason: str = data.get("reason", "")
    actor_id = int((g.current_user or {}).get("sub")) if getattr(g, "current_user", None) else None
    resp, code = change_status(actor_user_id=actor_id, req_id=req_id, new_status=new_status, reason=reason)
    return jsonify(resp), code


@admin_requests_bp.get("/requests/<int:req_id>")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.requests.api.read.all"])
def admin_get_request_detail(req_id: int):
    """
    Obtiene los detalles completos de una solicitud.

    Returns:
        JSON con todos los detalles de la solicitud
    """
    r = (
        db.session.query(Req)
        .options(
            joinedload(Req.appointment).joinedload(Appointment.coordinator).joinedload(Coordinator.user),
            joinedload(Req.appointment).joinedload(Appointment.slot),
            joinedload(Req.program),
            joinedload(Req.student),
            joinedload(Req.period),
        )
        .filter(Req.id == req_id)
        .first()
    )

    if not r:
        return jsonify({"error": "Solicitud no encontrada"}), 404

    a: Optional[Appointment] = r.appointment
    coord_name = None
    coord_email = None
    slot_info = None

    if a:
        if a.coordinator and a.coordinator.user:
            coord_name = a.coordinator.user.full_name
            coord_email = a.coordinator.user.email
        if a.slot:
            slot_info = {
                "day": a.slot.day.isoformat() if a.slot.day else None,
                "start_time": a.slot.start_time.strftime("%H:%M") if a.slot.start_time else None,
                "end_time": a.slot.end_time.strftime("%H:%M") if a.slot.end_time else None,
            }

    return jsonify({
        "id": r.id,
        "type": r.type,
        "status": r.status,
        "description": r.description,
        "coordinator_comment": r.coordinator_comment,
        "program": r.program.name if r.program else None,
        "program_id": r.program_id,
        "period": r.period.name if r.period else None,
        "period_id": r.period_id,
        "student": {
            "id": r.student.id if r.student else None,
            "name": r.student.full_name if r.student else None,
            "control_number": r.student.control_number if r.student and r.student.control_number else (r.student.username if r.student else None),
            "email": r.student.email if r.student else None,
        },
        "coordinator": {
            "name": coord_name,
            "email": coord_email,
        } if coord_name else None,
        "appointment": {
            "id": a.id,
            "status": a.status,
            "booked_at": a.booked_at.isoformat() if a.booked_at else None,
            "slot": slot_info,
        } if a else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    })


@admin_requests_bp.post("/requests/create")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.requests.api.create.all"])
def admin_create_request():
    """
    Permite a un admin crear una solicitud en nombre de un estudiante.

    Body JSON:
        student_id: ID del estudiante
        type: APPOINTMENT o DROP
        program_id: ID del programa
        description: Descripción de la solicitud
        slot_id: ID del slot (solo para APPOINTMENT)

    Returns:
        JSON con request_id y tipo
    """
    data = request.get_json(silent=True) or {}
    student_id = data.get("student_id")
    req_type = (data.get("type") or "").upper()
    program_id = data.get("program_id")
    description = data.get("description", "").strip()
    slot_id = data.get("slot_id")

    socketio = current_app.extensions.get('socketio')

    # Validaciones básicas
    if not student_id or not req_type or not program_id or not description:
        return jsonify({"error": "missing_fields", "message": "Faltan campos requeridos"}), 400

    if req_type not in ("APPOINTMENT", "DROP"):
        return jsonify({"error": "invalid_type", "message": "Tipo de solicitud inválido"}), 400

    # Obtener usuario (estudiante)
    student = db.session.query(User).get(student_id)
    if not student:
        return jsonify({"error": "student_not_found", "message": "Estudiante no encontrado"}), 404

    # Obtener período activo
    period = period_service.get_active_period()
    if not period:
        return jsonify({"error": "no_active_period", "message": "No hay un período académico activo"}), 503

    # Validar que el estudiante NO tenga ya una solicitud en este período
    existing_request = (
        db.session.query(Req)
        .filter(Req.student_id == student_id,
                Req.period_id == period.id,
                Req.status != "CANCELED")
        .first()
    )

    if existing_request:
        return jsonify({
            "error": "already_has_request_in_period",
            "message": f"El estudiante ya tiene una solicitud en el período '{period.name}'.",
            "existing_request_id": existing_request.id,
            "existing_request_status": existing_request.status
        }), 409

    # Tipo: DROP
    if req_type == "DROP":
        r = Req(
            student_id=student_id,
            program_id=program_id,
            period_id=period.id,
            description=description,
            type="DROP",
            status="PENDING"
        )
        db.session.add(r)
        db.session.commit()

        # Notificar a coordinadores del programa
        try:
            coord_ids = [
                row[0] for row in db.session.query(ProgramCoordinator.coordinator_id)
                                        .filter_by(program_id=program_id).all()
            ]
            payload = {
                "request_id": r.id,
                "student_id": student_id,
                "program_id": program_id,
                "status": r.status
            }
            for cid in coord_ids:
                broadcast_drop_created(socketio, cid, payload)
        except Exception:
            current_app.logger.exception("Failed to broadcast drop_created")

        # Notificar al estudiante
        try:
            n = create_notification(
                user_id=student_id,
                type="DROP_CREATED",
                title="Solicitud de baja creada",
                body="Tu solicitud de baja fue registrada por un administrador.",
                data={"request_id": r.id},
                source_request_id=r.id,
                program_id=program_id
            )
            db.session.commit()
            push_notification(socketio, student_id, n.to_dict())
        except Exception:
            current_app.logger.exception("Failed to create/push DROP notification")

        return jsonify({"ok": True, "request_id": r.id, "type": "DROP"})

    # Tipo: APPOINTMENT
    if req_type == "APPOINTMENT":
        if not slot_id:
            return jsonify({"error": "slot_id_required", "message": "Se requiere slot_id para APPOINTMENT"}), 400

        slot = db.session.query(TimeSlot).get(slot_id)
        if not slot or slot.is_booked:
            return jsonify({"error": "slot_unavailable", "message": "El horario no está disponible"}), 409

        enabled_days = set(period_service.get_enabled_days(period.id))
        if slot.day not in enabled_days:
            return jsonify({
                "error": "day_not_enabled",
                "message": "El día seleccionado no está habilitado"
            }), 400

        now = datetime.now()
        slot_datetime = datetime.combine(slot.day, slot.start_time)
        if now > slot_datetime:
            return jsonify({"error": "slot_time_passed", "message": "El horario ya pasó"}), 400

        link = (
            db.session.query(ProgramCoordinator)
            .filter(ProgramCoordinator.program_id == program_id,
                    ProgramCoordinator.coordinator_id == slot.coordinator_id)
            .first()
        )
        if not link:
            return jsonify({"error": "slot_not_for_program", "message": "El coordinador no está asignado al programa"}), 400

        try:
            updated = (
                db.session.query(TimeSlot)
                .filter(TimeSlot.id == slot_id, TimeSlot.is_booked == False)
                .update({TimeSlot.is_booked: True}, synchronize_session=False)
            )
            if updated != 1:
                db.session.rollback()
                return jsonify({"error": "slot_conflict", "message": "El horario fue reservado"}), 409

            r = Req(
                student_id=student_id,
                program_id=program_id,
                period_id=period.id,
                description=description,
                type="APPOINTMENT",
                status="PENDING"
            )
            db.session.add(r)
            db.session.flush()

            ap = Appointment(
                request_id=r.id,
                student_id=student_id,
                program_id=program_id,
                coordinator_id=slot.coordinator_id,
                slot_id=slot_id,
                status="SCHEDULED"
            )
            db.session.add(ap)
            db.session.commit()

            # Broadcast slot booked
            try:
                slot_day = str(slot.day)
                room = f"day:{slot_day}"
                socketio.emit("slot_booked", {
                    "slot_id": slot_id,
                    "day": slot_day,
                    "start_time": slot.start_time.strftime("%H:%M"),
                    "end_time": slot.end_time.strftime("%H:%M"),
                }, to=room, namespace="/slots")

                redis_cli = get_redis()
                redis_cli.delete(f"slot:{slot_id}:hold")
            except Exception:
                current_app.logger.exception("Failed to broadcast slot_booked")

            # Broadcast appointment created
            try:
                day_str = str(slot.day)
                payload = {
                    "request_id": r.id,
                    "student_id": student_id,
                    "program_id": program_id,
                    "slot_day": day_str,
                    "slot_start": slot.start_time.strftime("%H:%M"),
                    "slot_end": slot.end_time.strftime("%H:%M"),
                    "status": r.status
                }
                broadcast_appointment_created(socketio, ap.coordinator_id, day_str, payload)
            except Exception:
                current_app.logger.exception("Failed to broadcast appointment_created")

            # Notificar al estudiante
            try:
                slot_day = str(slot.day)
                n = create_notification(
                    user_id=student_id,
                    type="APPOINTMENT_CREATED",
                    title="Cita agendada",
                    body=f"Tu cita fue agendada: {slot_day} {slot.start_time.strftime('%H:%M')}–{slot.end_time.strftime('%H:%M')}",
                    data={"request_id": r.id, "appointment_id": ap.id, "day": slot_day},
                    source_request_id=r.id,
                    source_appointment_id=ap.id,
                    program_id=program_id
                )
                db.session.commit()
                push_notification(socketio, student_id, n.to_dict())
            except Exception:
                current_app.logger.exception("Failed to create/push APPOINTMENT notification")

            return jsonify({"ok": True, "request_id": r.id, "appointment_id": ap.id, "type": "APPOINTMENT"})

        except IntegrityError:
            db.session.rollback()
            return jsonify({"error": "conflict", "message": "Conflicto al crear la solicitud"}), 409

    return jsonify({"error": "invalid_request"}), 400
