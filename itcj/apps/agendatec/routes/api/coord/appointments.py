# routes/api/coord/appointments.py
"""
Endpoints para gestión de citas.

Incluye:
- coord_appointments: Listar citas del día
- update_appointment: Actualizar estado de cita
"""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, g, jsonify, request

from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.appointment import Appointment
from itcj.apps.agendatec.models.request import Request
from itcj.apps.agendatec.models.time_slot import TimeSlot
from itcj.core.models.coordinator import Coordinator
from itcj.core.models.program import Program
from itcj.core.models.program_coordinator import ProgramCoordinator
from itcj.core.models.user import User
from itcj.core.services import period_service
from itcj.core.sockets.requests import broadcast_request_status_changed
from itcj.core.utils.decorators import api_app_required, api_auth_required

from .helpers import get_current_coordinator_id, get_coord_program_ids

coord_appointments_bp = Blueprint("coord_appointments", __name__)


@coord_appointments_bp.get("/appointments")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.appointments.api.read.own"])
def coord_appointments():
    """
    Lista citas del coordinador para un día específico.

    Query params:
        day: Fecha en formato YYYY-MM-DD
        req_status: Filtro por estado de solicitud
        include_empty: Si "1", incluye todos los slots (vacíos y ocupados)
        request_id: Filtro por ID de solicitud específica
        program_id: Filtro por programa
        coordinator_id: Filtro por coordinador específico
        page, page_size: Paginación

    Returns:
        JSON con period, day, total, items y/o slots
    """
    coord_id = get_current_coordinator_id()
    if not coord_id:
        return jsonify({"error": "coordinator_not_found"}), 404

    day_s = (request.args.get("day") or "").strip()
    req_status = (request.args.get("req_status") or "").strip().upper()
    include_empty = (request.args.get("include_empty") or "0") in ("1", "true", "True")
    request_id = request.args.get("request_id")
    program_id = request.args.get("program_id")
    filter_coordinator_id = request.args.get("coordinator_id")
    page = int(request.args.get("page", 1))
    page_size = min(max(int(request.args.get("page_size", 200 if include_empty else 50)), 1), 500)

    try:
        d = datetime.strptime(day_s, "%Y-%m-%d").date()
    except Exception:
        return jsonify({"error": "invalid_day_format"}), 400

    # Validar que el día esté habilitado en el período activo
    period = period_service.get_active_period()
    if not period:
        return jsonify({"error": "no_active_period"}), 503

    enabled_days = set(period_service.get_enabled_days(period.id))
    if d not in enabled_days:
        return jsonify({"error": "day_not_allowed"}), 400

    # Obtener programas del coordinador para visibilidad compartida
    prog_ids = get_coord_program_ids(coord_id)

    # Base query
    base = (
        db.session.query(Appointment, TimeSlot, Program, Request, User)
        .join(TimeSlot, TimeSlot.id == Appointment.slot_id)
        .join(Program, Program.id == Appointment.program_id)
        .join(Request, Request.id == Appointment.request_id)
        .join(User, User.id == Appointment.student_id)
        .filter(Appointment.program_id.in_(prog_ids),
                TimeSlot.day == d)
    )

    # Filtro opcional por coordinador específico
    if filter_coordinator_id:
        try:
            filt_coord_id = int(filter_coordinator_id)
            filt_coord_prog_ids = get_coord_program_ids(filt_coord_id)
            if not prog_ids.intersection(filt_coord_prog_ids):
                return jsonify({"error": "forbidden_coordinator"}), 403
            base = base.filter(Appointment.coordinator_id == filt_coord_id)
        except ValueError:
            return jsonify({"error": "invalid_coordinator_id"}), 400

    if req_status:
        base = base.filter(Request.status == req_status)
    else:
        base = base.filter(Request.status != "CANCELED")

    if program_id:
        try:
            pid = int(program_id)
        except:
            return jsonify({"error": "invalid_program_id"}), 400
        if pid not in get_coord_program_ids(coord_id):
            return jsonify({"error": "forbidden_program"}), 403
        base = base.filter(Appointment.program_id == pid)

    if request_id:
        try:
            rid = int(request_id)
            base = base.filter(Request.id == rid)
        except:
            return jsonify({"error": "invalid_request_id"}), 400

    total = base.count()
    rows = (
        base.order_by(TimeSlot.start_time.asc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )

    items = []
    for ap, slot, prog, req, stu in rows:
        coord = db.session.query(Coordinator).get(ap.coordinator_id)
        coord_user = db.session.query(User).get(coord.user_id) if coord else None

        items.append({
            "appointment_id": ap.id,
            "request_id": req.id,
            "program": {"id": prog.id, "name": prog.name},
            "description": req.description,
            "coordinator_comment": req.coordinator_comment,
            "assigned_coordinator": {
                "id": ap.coordinator_id,
                "name": coord_user.full_name if coord_user else "Desconocido"
            },
            "student": {
                "id": stu.id,
                "full_name": stu.full_name,
                "control_number": stu.control_number,
                "username": stu.username
            },
            "slot": {
                "day": str(slot.day),
                "start_time": slot.start_time.strftime("%H:%M"),
                "end_time": slot.end_time.strftime("%H:%M")
            },
            "request_status": req.status
        })

    # Información del período
    period_info = {
        "id": period.id,
        "name": period.name,
        "start_date": period.start_date.isoformat(),
        "end_date": period.end_date.isoformat()
    }

    if not include_empty:
        return jsonify({
            "period": period_info,
            "day": str(d),
            "total": total,
            "items": items
        })

    # Vista tabla: devolver TODOS los slots del día
    if filter_coordinator_id:
        try:
            filt_coord_id = int(filter_coordinator_id)
            filt_coord_prog_ids = get_coord_program_ids(filt_coord_id)
            if not prog_ids.intersection(filt_coord_prog_ids):
                return jsonify({"error": "forbidden_coordinator"}), 403
            coord_ids_for_slots = [filt_coord_id]
        except ValueError:
            return jsonify({"error": "invalid_coordinator_id"}), 400
    else:
        coord_ids_for_slots = [
            pc.coordinator_id for pc in db.session.query(ProgramCoordinator)
            .filter(ProgramCoordinator.program_id.in_(prog_ids)).distinct().all()
        ]

    ts_q = (
        db.session.query(TimeSlot, Coordinator, User)
        .outerjoin(Coordinator, Coordinator.id == TimeSlot.coordinator_id)
        .outerjoin(User, User.id == Coordinator.user_id)
        .filter(TimeSlot.coordinator_id.in_(coord_ids_for_slots),
                TimeSlot.day == d)
        .order_by(TimeSlot.start_time.asc())
    )

    slots = []
    ap_by_slot = {}
    for ap, slot, prog, req, stu in rows:
        coord = db.session.query(Coordinator).get(ap.coordinator_id)
        coord_user = db.session.query(User).get(coord.user_id) if coord else None

        ap_by_slot[slot.id] = {
            "request_id": req.id,
            "program": {"id": prog.id, "name": prog.name},
            "description": req.description,
            "coordinator_comment": req.coordinator_comment,
            "assigned_coordinator": {
                "id": ap.coordinator_id,
                "name": coord_user.full_name if coord_user else "Desconocido"
            },
            "student": {
                "id": stu.id,
                "full_name": stu.full_name,
                "control_number": stu.control_number,
                "username": stu.username
            },
            "request_status": req.status
        }

    for s, c, u in ts_q.all():
        entry = {
            "slot_id": s.id,
            "coordinator_id": s.coordinator_id,
            "coordinator_name": u.full_name if u else "Desconocido",
            "start": datetime.combine(s.day, s.start_time).strftime("%H:%M"),
            "end": datetime.combine(s.day, s.end_time).strftime("%H:%M"),
            "appointment": ap_by_slot.get(s.id)
        }
        slots.append(entry)

    return jsonify({
        "period": period_info,
        "day": str(d),
        "slots": slots
    })


@coord_appointments_bp.patch("/appointments/<int:ap_id>")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.appointments.api.update.own"])
def update_appointment(ap_id: int):
    """
    Actualiza el estado de una cita.

    Body JSON:
        status: Nuevo estado (SCHEDULED, DONE, NO_SHOW, CANCELED)

    Returns:
        JSON con ok: True
    """
    coord_id = get_current_coordinator_id()
    socketio = current_app.extensions.get('socketio')
    if not coord_id:
        return jsonify({"error": "coordinator_not_found"}), 404

    ap = db.session.query(Appointment).get(ap_id)
    if not ap:
        return jsonify({"error": "appointment_not_found"}), 404

    # Verificar que el coordinador pertenece al programa de la cita
    prog_ids = get_coord_program_ids(coord_id)
    if ap.program_id not in prog_ids:
        return jsonify({"error": "forbidden_program"}), 403

    data = request.get_json(silent=True) or {}
    new_status = (data.get("status") or "").upper()
    if new_status not in {"SCHEDULED", "DONE", "NO_SHOW", "CANCELED"}:
        return jsonify({"error": "invalid_status"}), 400

    # Sincronizar Request.status
    req = db.session.query(Request).get(ap.request_id)
    if not req:
        return jsonify({"error": "request_not_found"}), 404

    # Transición
    if new_status == "SCHEDULED":
        req.status = "PENDING"
    elif new_status == "DONE":
        req.status = "RESOLVED_SUCCESS"
    elif new_status == "NO_SHOW":
        req.status = "NO_SHOW"
    elif new_status == "CANCELED":
        req.status = "CANCELED"
        slot = db.session.query(TimeSlot).get(ap.slot_id)
        if slot and slot.is_booked:
            slot.is_booked = False

    ap.status = new_status
    db.session.commit()

    slot = db.session.query(TimeSlot).get(ap.slot_id)
    payload = {
        "type": "APPOINTMENT",
        "request_id": ap.request_id,
        "new_status": req.status,
        "day": str(slot.day) if slot else None,
        "program_id": req.program.id
    }
    broadcast_request_status_changed(socketio, coord_id, payload)
    return jsonify({"ok": True})
