# routes/api/coord/drops.py
"""
Endpoints para gestión de bajas y cambio de estado de solicitudes.

Incluye:
- coord_drops: Listar bajas
- update_request_status: Actualizar estado de cualquier solicitud
"""
from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import case

from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.appointment import Appointment
from itcj.apps.agendatec.models.request import Request
from itcj.apps.agendatec.models.time_slot import TimeSlot
from itcj.core.models.user import User
from itcj.core.services import period_service
from itcj.core.sockets.notifications import push_notification
from itcj.core.sockets.requests import broadcast_request_status_changed
from itcj.core.utils.decorators import api_app_required, api_auth_required
from itcj.core.utils.notify import create_notification

from .helpers import get_current_coordinator_id, get_coord_program_ids

coord_drops_bp = Blueprint("coord_drops", __name__)


@coord_drops_bp.get("/drops")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.drops.api.read.own"])
def coord_drops():
    """
    Lista solicitudes de baja para los programas del coordinador.

    Query params:
        status: Filtro por estado (ALL, PENDING, etc.)
        program_id: Filtro por programa específico
        request_id: Filtro por ID de solicitud
        page, page_size: Paginación

    Returns:
        JSON con period, total e items
    """
    # ¿es admin?
    role = (g.current_user or {}).get("role")
    is_admin = (role == "admin")

    # Si NO es admin, necesitamos el coordinador y sus programas
    coord_id = None
    prog_ids = None
    if not is_admin:
        coord_id = get_current_coordinator_id()
        if not coord_id:
            return jsonify({"total": 0, "items": []})
        prog_ids = get_coord_program_ids(coord_id)
        if not prog_ids:
            return jsonify({"total": 0, "items": []})

    # Obtener período activo para filtrar
    period = period_service.get_active_period()
    if not period:
        return jsonify({"error": "no_active_period"}), 503

    status = (request.args.get("status") or "ALL").upper()
    program_id = request.args.get("program_id")
    request_id = request.args.get("request_id")
    page = int(request.args.get("page", 1))
    page_size = min(max(int(request.args.get("page_size", 20)), 1), 100)

    q = (
        db.session.query(Request, User)
        .join(User, User.id == Request.student_id)
        .filter(Request.type == "DROP",
                Request.period_id == period.id)
    )

    # Filtro de pertenencia por programa
    if not is_admin:
        if not prog_ids:
            return jsonify({"total": 0, "items": []})
        q = q.filter(Request.program_id.in_(list(prog_ids)))

    # Filtro por ID específico
    if request_id:
        try:
            rid = int(request_id)
        except:
            return jsonify({"error": "invalid_request_id"}), 400
        q = q.filter(Request.id == rid)

    # Filtro por estado
    if status != "ALL":
        q = q.filter(Request.status == status)
    else:
        q = q.filter(Request.status != "CANCELED")

    # Filtro por programa explícito
    if program_id:
        try:
            pid = int(program_id)
        except:
            return jsonify({"error": "invalid_program_id"}), 400
        if not is_admin and pid not in prog_ids:
            return jsonify({"error": "forbidden_program"}), 403
        q = q.filter(Request.program_id == pid)

    # Orden
    if status == "PENDING":
        q = q.order_by(Request.created_at.asc(), Request.id.asc())
    elif status == "ALL":
        q = q.order_by(
            case((Request.status == "PENDING", 0), else_=1),
            Request.created_at.asc(),
            Request.id.asc()
        )
    else:
        q = q.order_by(Request.created_at.asc(), Request.id.asc())

    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()

    items = [{
        "id": r.id,
        "status": r.status,
        "description": r.description,
        "created_at": r.created_at.isoformat(),
        "comment": r.coordinator_comment,
        "coordinator_comment": r.coordinator_comment,
        "student": {
            "id": u.id,
            "full_name": u.full_name,
            "control_number": u.control_number,
            "username": u.username
        }
    } for r, u in rows]

    # Información del período activo
    period_info = {
        "id": period.id,
        "name": period.name,
        "start_date": period.start_date.isoformat(),
        "end_date": period.end_date.isoformat()
    }

    return jsonify({
        "period": period_info,
        "total": total,
        "items": items
    })


@coord_drops_bp.patch("/requests/<int:req_id>/status")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.appointments.api.update.own", "agendatec.drops.api.update.own"])
def update_request_status(req_id: int):
    """
    Actualiza el estado de una solicitud (DROP o APPOINTMENT).

    Body JSON:
        status: Nuevo estado
        coordinator_comment: Comentario del coordinador (opcional)

    Returns:
        JSON con ok: True
    """
    coord_id = get_current_coordinator_id()
    if not coord_id:
        return jsonify({"error": "coordinator_not_found"}), 404

    r = db.session.query(Request).get(req_id)
    if not r:
        return jsonify({"error": "request_not_found"}), 404

    data = request.get_json(silent=True) or {}
    new_status = (data.get("status") or "").upper()
    allowed = {"RESOLVED_SUCCESS", "RESOLVED_NOT_COMPLETED", "NO_SHOW", "ATTENDED_OTHER_SLOT", "CANCELED"}
    socketio = current_app.extensions.get('socketio')

    if new_status not in allowed:
        return jsonify({"error": "invalid_status"}), 400

    if "coordinator_comment" in data:
        comment = (data.get("coordinator_comment")).strip()
        r.coordinator_comment = comment or None

    # Validar que el coordinador pertenece al programa de la solicitud
    prog_ids = get_coord_program_ids(coord_id)
    if r.program_id not in prog_ids:
        return jsonify({"error": "forbidden_program"}), 403

    # Actualizar estado de la solicitud
    r.status = new_status

    # Si es APPOINTMENT, reflejar en Appointment.status
    if r.type == "APPOINTMENT":
        ap = db.session.query(Appointment).filter(Appointment.request_id == r.id).first()
        if ap:
            if new_status in ("RESOLVED_SUCCESS", "RESOLVED_NOT_COMPLETED", "ATTENDED_OTHER_SLOT"):
                ap.status = "DONE"
            elif new_status == "NO_SHOW":
                ap.status = "NO_SHOW"
            elif new_status == "CANCELED":
                ap.status = "CANCELED"
                slot = db.session.query(TimeSlot).get(ap.slot_id)
                if slot and slot.is_booked:
                    slot.is_booked = False

    db.session.commit()

    day = None
    if r.type == "APPOINTMENT":
        ap = db.session.query(Appointment).filter(Appointment.request_id == r.id).first()
        if ap:
            s = db.session.query(TimeSlot).get(ap.slot_id)
            day = str(s.day) if s else None

    payload = {
        "type": r.type,
        "request_id": r.id,
        "new_status": r.status,
        "day": day,
        "program_id": r.program.id
    }
    broadcast_request_status_changed(socketio, coord_id, payload)

    # Notificar al estudiante
    try:
        stu_id = db.session.query(User.id).filter(User.id == Request.student_id, Request.id == r.id).scalar()
        if stu_id:
            title_map = {
                "RESOLVED_SUCCESS": "Tu solicitud fue atendida y resuelta",
                "RESOLVED_NOT_COMPLETED": "Tu solicitud fue atendida pero no se resolvió",
                "NO_SHOW": "Marcado como no asistió",
                "ATTENDED_OTHER_SLOT": "Asististe en otro horario",
                "CANCELED": "Tu solicitud fue cancelada"
            }
            type_map = {
                "APPOINTMENT": "CITA",
                "DROP": "BAJA",
            }
            n = create_notification(
                user_id=stu_id,
                type="REQUEST_STATUS_CHANGED",
                title=title_map.get(new_status, "Estado de solicitud actualizado"),
                body="Solicitud : " + type_map.get(r.type, "") +
                     (("\nComentarios : " + r.coordinator_comment) if r.coordinator_comment else " "),
                data={"request_id": r.id, "status": new_status},
                source_request_id=r.id,
                program_id=r.program_id
            )
            db.session.commit()
            push_notification(socketio, stu_id, n.to_dict())
    except Exception:
        current_app.logger.exception("Failed to create/push status-change notification")

    return jsonify({"ok": True})
