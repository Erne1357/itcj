"""
Availability API v2 — Slots y ventanas de disponibilidad.
Fuente: itcj/apps/agendatec/routes/api/availability.py
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from itcj2.apps.agendatec.schemas.availability import CreateWindowBody, GenerateSlotsBody
from itcj2.dependencies import DbSession, require_perms, require_roles
from itcj2.apps.agendatec.helpers import parse_date_str

from itcj2.apps.agendatec.models.availability_window import AvailabilityWindow
from itcj2.apps.agendatec.models.time_slot import TimeSlot
from itcj2.core.models.coordinator import Coordinator
from itcj2.core.models.program import Program
from itcj2.core.models.program_coordinator import ProgramCoordinator
from itcj2.core.models.user import User
from itcj2.core.services import period_service

router = APIRouter(tags=["agendatec-availability"])
logger = logging.getLogger(__name__)

_VALID_SLOT_MINUTES = (5, 10, 15, 20, 30, 60)


def _get_enabled_days_for_active_period() -> set[date]:
    period = period_service.get_active_period()
    if not period:
        return set()
    return set(period_service.get_enabled_days(period.id))


def _require_allowed_day(d: date) -> None:
    """Lanza 400 si el día no está habilitado en el período activo."""
    period = period_service.get_active_period()
    if not period:
        raise HTTPException(status_code=503, detail="no_active_period")
    enabled = set(period_service.get_enabled_days(period.id))
    if d not in enabled:
        raise HTTPException(
            status_code=400,
            detail={"error": "day_not_allowed", "allowed": [str(x) for x in sorted(enabled)]},
        )


def _resolve_coordinator_id(user: dict, db: DbSession, override_id: Optional[int] = None) -> Optional[int]:
    """
    Si el usuario es coordinador, retorna su coordinator_id.
    Si se pasa override_id (para admins), lo usa como fallback.
    """
    uid = int(user["sub"])
    u = db.query(User).get(uid)
    if u:
        c = db.query(Coordinator).filter_by(user_id=u.id).first()
        if c:
            return c.id
    return override_id


# ==================== GET /program/<program_id>/slots ====================

@router.get("/program/{program_id}/slots")
def list_slots_for_program_day(
    program_id: int,
    day: Optional[str] = Query(None, description="Fecha YYYY-MM-DD (default: hoy)"),
    user: dict = require_roles("agendatec", ["student"]),
    db: DbSession = None,
):
    """Lista slots libres para un programa en un día específico."""
    if day:
        d = parse_date_str(day)
        if not d:
            raise HTTPException(status_code=400, detail="invalid_day_format")
    else:
        d = date.today()

    prog = db.query(Program).get(program_id)
    if not prog:
        raise HTTPException(status_code=404, detail="program_not_found")

    coor_ids = [
        pc.coordinator_id
        for pc in db.query(ProgramCoordinator)
        .filter(ProgramCoordinator.program_id == program_id)
        .all()
    ]
    if not coor_ids:
        return {"day": str(d), "program_id": program_id, "items": []}

    slots = (
        db.query(TimeSlot)
        .filter(
            TimeSlot.coordinator_id.in_(coor_ids),
            TimeSlot.day == d,
            TimeSlot.is_booked == False,
        )
        .order_by(TimeSlot.start_time.asc())
        .all()
    )

    coordinators_info = {}
    if len(coor_ids) > 1:
        coords = (
            db.query(Coordinator, User)
            .join(User, User.id == Coordinator.user_id)
            .filter(Coordinator.id.in_(coor_ids))
            .all()
        )
        coordinators_info = {c.id: u.full_name for c, u in coords}

    items = [
        {
            "slot_id": s.id,
            "coordinator_id": s.coordinator_id,
            "coordinator_name": coordinators_info.get(s.coordinator_id) if coordinators_info else None,
            "day": str(s.day),
            "start_time": s.start_time.strftime("%H:%M"),
            "end_time": s.end_time.strftime("%H:%M"),
        }
        for s in slots
    ]

    response = {"day": str(d), "program_id": program_id, "items": items}
    if coordinators_info:
        response["coordinators"] = [
            {"id": cid, "name": name} for cid, name in coordinators_info.items()
        ]
    return response


# ==================== POST /windows ====================

@router.post("/windows", status_code=201)
def create_availability_window(
    body: CreateWindowBody,
    user: dict = require_perms("agendatec", ["agendatec.slots.api.create"]),
    db: DbSession = None,
):
    """Crea una ventana de disponibilidad para un coordinador."""
    d = parse_date_str(body.day)
    if not d:
        raise HTTPException(status_code=400, detail="invalid_day_format")

    _require_allowed_day(d)

    coord_id = _resolve_coordinator_id(user, db, override_id=body.coordinator_id)
    if not coord_id:
        raise HTTPException(status_code=404, detail="coordinator_not_found")

    try:
        sh, sm = map(int, body.start.split(":"))
        eh, em = map(int, body.end.split(":"))
        start_t = datetime.strptime(f"{sh:02d}:{sm:02d}", "%H:%M").time()
        end_t = datetime.strptime(f"{eh:02d}:{em:02d}", "%H:%M").time()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_time_format")

    if end_t <= start_t or body.slot_minutes not in _VALID_SLOT_MINUTES:
        raise HTTPException(status_code=400, detail="invalid_time_range_or_slot_size")

    av = AvailabilityWindow(
        coordinator_id=coord_id,
        day=d,
        start_time=start_t,
        end_time=end_t,
        slot_minutes=body.slot_minutes,
    )
    db.add(av)
    db.commit()
    return {"ok": True, "id": av.id}


# ==================== POST /generate-slots ====================

@router.post("/generate-slots")
def generate_slots(
    body: GenerateSlotsBody,
    user: dict = require_perms("agendatec", ["agendatec.slots.api.create"]),
    db: DbSession = None,
):
    """Genera time_slots a partir de availability_windows para uno o más días."""
    days_input = body.days or ([body.day] if body.day else None)
    if not days_input:
        raise HTTPException(status_code=400, detail="invalid_payload_days")

    period = period_service.get_active_period()
    enabled_days = set(period_service.get_enabled_days(period.id)) if period else set()

    parsed_days: list[date] = []
    for s in days_input:
        d = parse_date_str(str(s))
        if not d:
            raise HTTPException(status_code=400, detail="invalid_day_format")
        if d not in enabled_days:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "day_not_allowed",
                    "day": str(d),
                    "allowed": [str(x) for x in sorted(enabled_days)],
                },
            )
        parsed_days.append(d)

    created = 0
    for d in parsed_days:
        wins = db.query(AvailabilityWindow).filter(AvailabilityWindow.day == d).all()
        for w in wins:
            step = timedelta(minutes=w.slot_minutes)
            cur_dt = datetime.combine(w.day, w.start_time)
            end_dt = datetime.combine(w.day, w.end_time)

            while (cur_dt + step) <= end_dt:
                start_t = cur_dt.time()
                end_t = (cur_dt + step).time()

                exists = (
                    db.query(TimeSlot.id)
                    .filter(
                        TimeSlot.coordinator_id == w.coordinator_id,
                        TimeSlot.day == w.day,
                        TimeSlot.start_time == start_t,
                    )
                    .first()
                )
                if not exists:
                    db.add(
                        TimeSlot(
                            coordinator_id=w.coordinator_id,
                            day=w.day,
                            start_time=start_t,
                            end_time=end_t,
                            is_booked=False,
                        )
                    )
                    created += 1

                cur_dt += step

    db.commit()
    return {"ok": True, "slots_created": created, "days": [str(d) for d in parsed_days]}


# ==================== GET /windows ====================

@router.get("/windows")
def list_my_windows(
    day: Optional[str] = Query(None, description="Fecha YYYY-MM-DD"),
    coordinator_id: Optional[int] = Query(None),
    user: dict = require_perms("agendatec", ["agendatec.slots.api.read"]),
    db: DbSession = None,
):
    """Lista ventanas de disponibilidad del coordinador para un día."""
    if day:
        d = parse_date_str(day)
        if not d:
            raise HTTPException(status_code=400, detail="invalid_day_format")
    else:
        d = date.today()

    _require_allowed_day(d)

    cid = _resolve_coordinator_id(user, db, override_id=coordinator_id)
    if not cid:
        raise HTTPException(status_code=404, detail="coordinator_not_found")

    wins = (
        db.query(AvailabilityWindow)
        .filter(AvailabilityWindow.coordinator_id == cid, AvailabilityWindow.day == d)
        .order_by(AvailabilityWindow.start_time.asc())
        .all()
    )

    items = [
        {
            "id": w.id,
            "coordinator_id": w.coordinator_id,
            "day": str(w.day),
            "start_time": w.start_time.strftime("%H:%M"),
            "end_time": w.end_time.strftime("%H:%M"),
            "slot_minutes": w.slot_minutes,
        }
        for w in wins
    ]
    return {"day": str(d), "coordinator_id": cid, "items": items}
