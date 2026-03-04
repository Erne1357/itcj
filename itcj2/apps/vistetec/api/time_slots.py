"""
Time Slots API v2 — 10 endpoints (horarios, signup de voluntarios, gestión).
Fuente: itcj/apps/vistetec/routes/api/time_slots.py
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.vistetec.schemas.time_slots import CreateScheduleBody, UpdateSlotBody

router = APIRouter(tags=["vistetec-slots"])
logger = logging.getLogger(__name__)


# ── Queries ───────────────────────────────────────────────────────────────────

@router.get("")
def list_available_slots(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    location_id: Optional[int] = None,
    user: dict = require_perms("vistetec", ["vistetec.slots.api.view_available"]),
    db: DbSession = None,
):
    """Lista slots disponibles para estudiantes."""
    from itcj2.apps.vistetec.services import time_slot_service

    parsed_from = datetime.fromisoformat(from_date).date() if from_date else None
    parsed_to = datetime.fromisoformat(to_date).date() if to_date else None

    slots = time_slot_service.get_available_slots(
        db,
        from_date=parsed_from,
        to_date=parsed_to,
        location_id=location_id,
    )
    return [s.to_dict() for s in slots]


@router.get("/all")
def list_all_slots(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    location_id: Optional[int] = None,
    user: dict = require_perms("vistetec", ["vistetec.slots.api.view_own"]),
    db: DbSession = None,
):
    """Lista todos los slots activos futuros para voluntarios (con estado de inscripción)."""
    from itcj2.apps.vistetec.services import time_slot_service

    parsed_from = datetime.fromisoformat(from_date).date() if from_date else None
    parsed_to = datetime.fromisoformat(to_date).date() if to_date else None

    slots = time_slot_service.get_all_slots(
        db,
        from_date=parsed_from,
        to_date=parsed_to,
        location_id=location_id,
    )

    volunteer_id = int(user["sub"])
    result = []
    for s in slots:
        data = s.to_dict(include_volunteers=True)
        data["is_signed_up"] = time_slot_service.is_volunteer_signed_up(db, s.id, volunteer_id)
        result.append(data)

    return result


@router.get("/calendar")
def get_calendar_slots(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    user: dict = require_perms("vistetec", ["vistetec.slots.api.view_available"]),
    db: DbSession = None,
):
    """Slots agrupados por fecha para vista de calendario."""
    from itcj2.apps.vistetec.services import time_slot_service

    if not from_date or not to_date:
        raise HTTPException(
            400,
            detail={"error": "missing_dates", "message": "Se requieren from_date y to_date"},
        )

    return time_slot_service.get_slots_for_date_range(
        db,
        datetime.fromisoformat(from_date).date(),
        datetime.fromisoformat(to_date).date(),
    )


@router.get("/locations")
def list_locations(
    user: dict = require_perms("vistetec", ["vistetec.slots.api.view_available"]),
    db: DbSession = None,
):
    """Lista ubicaciones disponibles."""
    from itcj2.apps.vistetec.services import time_slot_service

    locations = time_slot_service.get_locations(db)
    return [loc.to_dict() for loc in locations]


@router.get("/my-slots")
def list_my_signups(
    include_past: bool = False,
    user: dict = require_perms("vistetec", ["vistetec.slots.api.view_own"]),
    db: DbSession = None,
):
    """Lista slots donde estoy inscrito como voluntario."""
    from itcj2.apps.vistetec.services import time_slot_service

    slots = time_slot_service.get_volunteer_signups(
        db,
        volunteer_id=int(user["sub"]),
        include_past=include_past,
    )
    return [s.to_dict(include_volunteers=True) for s in slots]


# ── Creación de horario ───────────────────────────────────────────────────────

@router.post("", status_code=201)
def create_schedule(
    body: CreateScheduleBody,
    user: dict = require_perms("vistetec", ["vistetec.slots.api.create"]),
    db: DbSession = None,
):
    """Crea horarios dividiendo un bloque en slots por duración."""
    from itcj2.apps.vistetec.services import time_slot_service

    try:
        start_date = datetime.fromisoformat(body.start_date).date()
        end_date = datetime.fromisoformat(body.end_date).date()
        start_time = datetime.strptime(body.start_time, "%H:%M").time()
        end_time = datetime.strptime(body.end_time, "%H:%M").time()

        slots = time_slot_service.create_schedule_slots(
            db,
            created_by_id=int(user["sub"]),
            start_date=start_date,
            end_date=end_date,
            weekdays=body.weekdays,
            start_time=start_time,
            end_time=end_time,
            slot_duration_minutes=body.slot_duration_minutes,
            max_students_per_slot=body.max_students_per_slot,
            location_id=body.location_id,
        )
        logger.info(f"{len(slots)} slots creados por usuario {int(user['sub'])}")
        return {"created": len(slots), "slots": [s.to_dict() for s in slots]}
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


# ── Volunteer signup ──────────────────────────────────────────────────────────

@router.post("/{slot_id}/signup", status_code=201)
def signup_for_slot(
    slot_id: int,
    user: dict = require_perms("vistetec", ["vistetec.slots.api.signup"]),
    db: DbSession = None,
):
    """Voluntario se inscribe a un slot."""
    from itcj2.apps.vistetec.services import time_slot_service

    try:
        sv = time_slot_service.signup_volunteer(
            db,
            slot_id=slot_id,
            volunteer_id=int(user["sub"]),
        )
        return {"message": "Inscrito al horario", "signup": sv.to_dict()}
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


@router.post("/{slot_id}/unsignup")
def unsignup_from_slot(
    slot_id: int,
    user: dict = require_perms("vistetec", ["vistetec.slots.api.signup"]),
    db: DbSession = None,
):
    """Voluntario cancela su inscripción a un slot."""
    from itcj2.apps.vistetec.services import time_slot_service

    try:
        time_slot_service.unsignup_volunteer(
            db,
            slot_id=slot_id,
            volunteer_id=int(user["sub"]),
        )
        return {"message": "Inscripción cancelada"}
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


# ── Gestión de slots ──────────────────────────────────────────────────────────

@router.put("/{slot_id}")
def update_slot(
    slot_id: int,
    body: UpdateSlotBody,
    user: dict = require_perms("vistetec", ["vistetec.slots.api.update"]),
    db: DbSession = None,
):
    """Actualiza un slot (solo el creador)."""
    from itcj2.apps.vistetec.services import time_slot_service

    data = body.model_dump(exclude_none=True)

    try:
        if "date" in data:
            data["date"] = datetime.fromisoformat(data["date"]).date()
        if "start_time" in data:
            data["start_time"] = datetime.strptime(data["start_time"], "%H:%M").time()
        if "end_time" in data:
            data["end_time"] = datetime.strptime(data["end_time"], "%H:%M").time()

        slot = time_slot_service.update_slot(
            db,
            slot_id=slot_id,
            user_id=int(user["sub"]),
            **data,
        )
        return slot.to_dict()
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})


@router.delete("/{slot_id}")
def cancel_slot(
    slot_id: int,
    user: dict = require_perms("vistetec", ["vistetec.slots.api.delete"]),
    db: DbSession = None,
):
    """Cancela un slot (solo el creador)."""
    from itcj2.apps.vistetec.services import time_slot_service

    try:
        slot = time_slot_service.cancel_slot(
            db,
            slot_id=slot_id,
            user_id=int(user["sub"]),
        )
        logger.info(f"Slot {slot_id} cancelado por usuario {int(user['sub'])}")
        return {"message": "Slot cancelado", "slot": slot.to_dict()}
    except ValueError as e:
        raise HTTPException(400, detail={"error": "validation_error", "message": str(e)})
