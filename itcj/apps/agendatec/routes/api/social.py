# routes/api/social.py
from datetime import datetime
from flask import Blueprint, request, jsonify
from sqlalchemy import and_
from itcj.core.utils.decorators import api_auth_required, api_role_required
from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.time_slot import TimeSlot
from itcj.apps.agendatec.models.appointment import Appointment
from itcj.apps.agendatec.models.request import Request
from itcj.core.models.program import Program
from itcj.core.models.user import User

api_social_bp = Blueprint("api_social", __name__)

@api_social_bp.get("/social/appointments")
@api_auth_required
@api_role_required(["social_service"])  # restringido a Servicio Social
def social_appointments():
    """
    Lista citas por día (obligatorio) y carrera opcional (program_id).
    Solo expone: Horario (start-end) y Nombre del alumno.
    Muestra citas con Request.status != 'CANCELED' (por defecto) y Appointment.status != 'CANCELED'.
    """
    day_s = (request.args.get("day") or "").strip()
    if not day_s:
        return jsonify({"error": "missing_day"}), 400

    try:
        d = datetime.strptime(day_s, "%Y-%m-%d").date()
    except Exception:
        return jsonify({"error": "invalid_day_format"}), 400

    program_id = request.args.get("program_id")
    pid = None
    if program_id:
        try:
            pid = int(program_id)
        except Exception:
            return jsonify({"error": "invalid_program_id"}), 400

    q = (db.session.query(Appointment, TimeSlot, Request, User, Program)
         .join(TimeSlot, TimeSlot.id == Appointment.slot_id)
         .join(Request, Request.id == Appointment.request_id)
         .join(User, User.id == Appointment.student_id)
         .join(Program, Program.id == Appointment.program_id)
         .filter(TimeSlot.day == d))

    # Filtrar por programa si se envía
    if pid:
        q = q.filter(Appointment.program_id == pid)

    # Ocultar canceladas (y opcionalmente no pendientes si lo quieres ultra-minimal)
    q = q.filter(Request.status != "CANCELED")
    q = q.filter(Appointment.status != "CANCELED")

    rows = (q.order_by(TimeSlot.start_time.asc()).all())

    items = []
    for ap, slot, req, stu, prog in rows:
        items.append({
            "time": f"{slot.start_time.strftime('%H:%M')}–{slot.end_time.strftime('%H:%M')}",
            "student_name": stu.full_name or stu.username or "—",
            # Metadatos mínimos por si el cliente los requiere (no se imprimen):
            "program_id": prog.id,
            "day": str(slot.day),
        })

    return jsonify({"day": str(d), "total": len(items), "items": items})
