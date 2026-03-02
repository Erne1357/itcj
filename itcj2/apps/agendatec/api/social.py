"""
Social API v2 — Citas para servicio social.
Fuente: itcj/apps/agendatec/routes/api/social.py
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.agendatec.models.appointment import Appointment
from itcj2.apps.agendatec.models.request import Request
from itcj2.apps.agendatec.models.time_slot import TimeSlot
from itcj2.core.models.program import Program
from itcj2.core.models.user import User

router = APIRouter(tags=["agendatec-social"])
logger = logging.getLogger(__name__)

CurrentPerms = require_perms("agendatec", ["agendatec.social.api.read.appointments"])


@router.get("/appointments")
def social_appointments(
    day: str = Query(..., description="Fecha YYYY-MM-DD"),
    program_id: Optional[int] = Query(None),
    user: dict = CurrentPerms,
    db: DbSession = None,
):
    """
    Lista citas del día (obligatorio) filtrando por carrera opcional.
    Solo expone: Horario y Nombre del alumno.
    Excluye citas y solicitudes canceladas.
    """
    try:
        d = datetime.strptime(day.strip(), "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_day_format")

    q = (
        db.query(Appointment, TimeSlot, Request, User, Program)
        .join(TimeSlot, TimeSlot.id == Appointment.slot_id)
        .join(Request, Request.id == Appointment.request_id)
        .join(User, User.id == Appointment.student_id)
        .join(Program, Program.id == Appointment.program_id)
        .filter(TimeSlot.day == d)
    )

    if program_id:
        q = q.filter(Appointment.program_id == program_id)

    q = q.filter(Request.status != "CANCELED", Appointment.status != "CANCELED")
    rows = q.order_by(TimeSlot.start_time.asc()).all()

    items = [
        {
            "time": f"{slot.start_time.strftime('%H:%M')}–{slot.end_time.strftime('%H:%M')}",
            "student_name": stu.full_name or stu.username or "—",
            "program_id": prog.id,
            "day": str(slot.day),
        }
        for ap, slot, req, stu, prog in rows
    ]

    return {"day": str(d), "total": len(items), "items": items}
