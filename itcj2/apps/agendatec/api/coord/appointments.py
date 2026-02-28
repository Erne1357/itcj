"""
Coord Appointments API v2 — Citas del coordinador.
Fuente: itcj/apps/agendatec/routes/api/coord/appointments.py
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.agendatec.helpers import require_coordinator, get_coord_program_ids
from itcj2.apps.agendatec.schemas.coord import UpdateAppointmentBody
from itcj.apps.agendatec.models.appointment import Appointment
from itcj.apps.agendatec.models.request import Request
from itcj.apps.agendatec.models.time_slot import TimeSlot
from itcj.core.models.coordinator import Coordinator
from itcj.core.models.program import Program
from itcj.core.models.program_coordinator import ProgramCoordinator
from itcj.core.models.user import User
from itcj.core.services import period_service

router = APIRouter(tags=["agendatec-coord-appointments"])
logger = logging.getLogger(__name__)

ReadPerm = require_perms("agendatec", ["agendatec.appointments.api.read.own"])
UpdatePerm = require_perms("agendatec", ["agendatec.appointments.api.update.own"])


# ==================== GET /appointments ====================

@router.get("/appointments")
def coord_appointments(
    day: str = Query(..., description="Fecha YYYY-MM-DD"),
    req_status: str = Query(""),
    include_empty: bool = Query(False),
    request_id: Optional[int] = Query(None),
    program_id: Optional[int] = Query(None),
    coordinator_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user: dict = ReadPerm,
    db: DbSession = None,
):
    """Lista citas del coordinador para un día específico."""
    coord_id = require_coordinator(int(user["sub"]), db)

    try:
        d = datetime.strptime(day.strip(), "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_day_format")

    period = period_service.get_active_period()
    if not period:
        raise HTTPException(status_code=503, detail="no_active_period")

    enabled_days = set(period_service.get_enabled_days(period.id))
    if d not in enabled_days:
        raise HTTPException(status_code=400, detail="day_not_allowed")

    if include_empty:
        page_size = min(page_size, 500) if page_size > 50 else 200

    prog_ids = get_coord_program_ids(coord_id, db)

    base = (
        db.query(Appointment, TimeSlot, Program, Request, User)
        .join(TimeSlot, TimeSlot.id == Appointment.slot_id)
        .join(Program, Program.id == Appointment.program_id)
        .join(Request, Request.id == Appointment.request_id)
        .join(User, User.id == Appointment.student_id)
        .filter(Appointment.program_id.in_(prog_ids), TimeSlot.day == d)
    )

    # Filtro por coordinador específico
    filt_coord_prog_ids = None
    if coordinator_id:
        filt_coord_prog_ids = get_coord_program_ids(coordinator_id, db)
        if not prog_ids.intersection(filt_coord_prog_ids):
            raise HTTPException(status_code=403, detail="forbidden_coordinator")
        base = base.filter(Appointment.coordinator_id == coordinator_id)

    req_status_upper = req_status.strip().upper()
    if req_status_upper:
        base = base.filter(Request.status == req_status_upper)
    else:
        base = base.filter(Request.status != "CANCELED")

    if program_id:
        if program_id not in prog_ids:
            raise HTTPException(status_code=403, detail="forbidden_program")
        base = base.filter(Appointment.program_id == program_id)

    if request_id:
        base = base.filter(Request.id == request_id)

    total = base.count()
    rows = (
        base.order_by(TimeSlot.start_time.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    def _row_to_item(ap, slot, prog, req, stu):
        coord = db.query(Coordinator).get(ap.coordinator_id)
        coord_user = db.query(User).get(coord.user_id) if coord else None
        return {
            "appointment_id": ap.id,
            "request_id": req.id,
            "program": {"id": prog.id, "name": prog.name},
            "description": req.description,
            "coordinator_comment": req.coordinator_comment,
            "assigned_coordinator": {
                "id": ap.coordinator_id,
                "name": coord_user.full_name if coord_user else "Desconocido",
            },
            "student": {
                "id": stu.id,
                "full_name": stu.full_name,
                "control_number": stu.control_number,
                "username": stu.username,
            },
            "slot": {
                "day": str(slot.day),
                "start_time": slot.start_time.strftime("%H:%M"),
                "end_time": slot.end_time.strftime("%H:%M"),
            },
            "request_status": req.status,
        }

    items = [_row_to_item(ap, slot, prog, req, stu) for ap, slot, prog, req, stu in rows]

    period_info = {
        "id": period.id,
        "name": period.name,
        "start_date": period.start_date.isoformat(),
        "end_date": period.end_date.isoformat(),
    }

    if not include_empty:
        return {"period": period_info, "day": str(d), "total": total, "items": items}

    # Vista tabla: devolver TODOS los slots del día
    if coordinator_id:
        coord_ids_for_slots = [coordinator_id]
    else:
        coord_ids_for_slots = list({
            pc.coordinator_id
            for pc in db.query(ProgramCoordinator)
            .filter(ProgramCoordinator.program_id.in_(prog_ids))
            .all()
        })

    ts_q = (
        db.query(TimeSlot, Coordinator, User)
        .outerjoin(Coordinator, Coordinator.id == TimeSlot.coordinator_id)
        .outerjoin(User, User.id == Coordinator.user_id)
        .filter(TimeSlot.coordinator_id.in_(coord_ids_for_slots), TimeSlot.day == d)
        .order_by(TimeSlot.start_time.asc())
    )

    ap_by_slot = {slot.id: _row_to_item(ap, slot, prog, req, stu) for ap, slot, prog, req, stu in rows}
    # Remove appointment-specific keys; keep as-is for slot map

    slots = [
        {
            "slot_id": s.id,
            "coordinator_id": s.coordinator_id,
            "coordinator_name": u.full_name if u else "Desconocido",
            "start": s.start_time.strftime("%H:%M"),
            "end": s.end_time.strftime("%H:%M"),
            "appointment": ap_by_slot.get(s.id),
        }
        for s, c, u in ts_q.all()
    ]

    return {"period": period_info, "day": str(d), "slots": slots}


# ==================== PATCH /appointments/<ap_id> ====================

@router.patch("/appointments/{ap_id}")
async def update_appointment(
    ap_id: int,
    body: UpdateAppointmentBody,
    user: dict = UpdatePerm,
    db: DbSession = None,
):
    """Actualiza el estado de una cita."""
    coord_id = require_coordinator(int(user["sub"]), db)

    ap = db.query(Appointment).get(ap_id)
    if not ap:
        raise HTTPException(status_code=404, detail="appointment_not_found")

    prog_ids = get_coord_program_ids(coord_id, db)
    if ap.program_id not in prog_ids:
        raise HTTPException(status_code=403, detail="forbidden_program")

    new_status = (body.status or "").upper()
    if new_status not in {"SCHEDULED", "DONE", "NO_SHOW", "CANCELED"}:
        raise HTTPException(status_code=400, detail="invalid_status")

    req = db.query(Request).get(ap.request_id)
    if not req:
        raise HTTPException(status_code=404, detail="request_not_found")

    if new_status == "SCHEDULED":
        req.status = "PENDING"
    elif new_status == "DONE":
        req.status = "RESOLVED_SUCCESS"
    elif new_status == "NO_SHOW":
        req.status = "NO_SHOW"
    elif new_status == "CANCELED":
        req.status = "CANCELED"
        slot = db.query(TimeSlot).get(ap.slot_id)
        if slot and slot.is_booked:
            slot.is_booked = False

    ap.status = new_status
    db.commit()

    try:
        from itcj2.sockets.requests import broadcast_request_status_changed
        slot = db.query(TimeSlot).get(ap.slot_id)
        await broadcast_request_status_changed(coord_id, {
            "type": "APPOINTMENT",
            "request_id": ap.request_id,
            "new_status": req.status,
            "day": str(slot.day) if slot else None,
            "program_id": req.program.id if req.program else None,
        })
    except Exception:
        logger.exception("Failed to broadcast request_status_changed")

    return {"ok": True}
