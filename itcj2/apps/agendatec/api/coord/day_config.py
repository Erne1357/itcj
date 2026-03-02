"""
Coord Day Config API v2 — Configuración de días y slots.
Fuente: itcj/apps/agendatec/routes/api/coord/day_config.py
"""
import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.agendatec.helpers import require_coordinator, split_or_delete_windows, parse_time_str
from itcj2.apps.agendatec.schemas.coord import SetDayConfigBody, DeleteDayRangeBody
from itcj2.apps.agendatec.models.availability_window import AvailabilityWindow
from itcj2.apps.agendatec.models.time_slot import TimeSlot
from itcj2.core.services import period_service

router = APIRouter(tags=["agendatec-coord-day-config"])
logger = logging.getLogger(__name__)

ReadPerm = require_perms("agendatec", ["agendatec.slots.api.read"])
CreatePerm = require_perms("agendatec", ["agendatec.slots.api.create"])
DeletePerm = require_perms("agendatec", ["agendatec.slots.api.delete"])


def _get_active_period_and_days():
    """Helper: retorna (period, enabled_days_set) o lanza 503."""
    period = period_service.get_active_period()
    if not period:
        raise HTTPException(status_code=503, detail="no_active_period")
    enabled = set(period_service.get_enabled_days(period.id))
    return period, enabled


def _parse_day(day_s: str) -> date:
    try:
        return datetime.strptime(day_s.strip(), "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_day_format")


# ==================== GET /day-config ====================

@router.get("/day-config")
def get_day_config(
    day: str = Query(..., description="Fecha YYYY-MM-DD"),
    user: dict = ReadPerm,
    db: DbSession = None,
):
    """Obtiene la configuración de ventanas de disponibilidad para un día."""
    coord_id = require_coordinator(int(user["sub"]), db)
    d = _parse_day(day)

    _, enabled = _get_active_period_and_days()
    if d not in enabled:
        raise HTTPException(
            status_code=400,
            detail={"error": "day_not_allowed", "allowed": [str(x) for x in sorted(enabled)]},
        )

    wins = (
        db.query(AvailabilityWindow)
        .filter(AvailabilityWindow.coordinator_id == coord_id, AvailabilityWindow.day == d)
        .order_by(AvailabilityWindow.start_time.asc())
        .all()
    )

    return {
        "day": str(d),
        "items": [
            {
                "id": w.id,
                "day": str(w.day),
                "start": w.start_time.strftime("%H:%M"),
                "end": w.end_time.strftime("%H:%M"),
                "slot_minutes": w.slot_minutes,
            }
            for w in wins
        ],
    }


# ==================== POST /day-config ====================

@router.post("/day-config")
def set_day_config(
    body: SetDayConfigBody,
    user: dict = CreatePerm,
    db: DbSession = None,
):
    """Agrega/actualiza una ventana de disponibilidad para un día."""
    coord_id = require_coordinator(int(user["sub"]), db)
    d = _parse_day(body.day)

    _, enabled = _get_active_period_and_days()
    if d not in enabled:
        raise HTTPException(
            status_code=400,
            detail={"error": "day_not_allowed", "allowed": [str(x) for x in sorted(enabled)]},
        )

    start_t = parse_time_str(body.start)
    end_t = parse_time_str(body.end)
    if not start_t or not end_t:
        raise HTTPException(status_code=400, detail="invalid_time_format")

    if datetime.now() > datetime.combine(d, start_t):
        raise HTTPException(status_code=400, detail="slot_time_passed")

    if end_t <= start_t or body.slot_minutes not in (5, 10, 15, 20, 30, 60):
        raise HTTPException(status_code=400, detail="invalid_time_range_or_slot_size")

    # Verificar que no hay reservas en el rango
    booked_cnt = (
        db.query(TimeSlot.id)
        .filter(
            TimeSlot.coordinator_id == coord_id,
            TimeSlot.day == d,
            TimeSlot.start_time >= start_t,
            TimeSlot.start_time < end_t,
            TimeSlot.is_booked == True,
        )
        .count()
    )
    if booked_cnt > 0:
        raise HTTPException(status_code=409, detail={"error": "overlap_booked_slots_exist", "booked_count": booked_cnt})

    # Eliminar ventanas solapadas
    overlapping = (
        db.query(AvailabilityWindow)
        .filter(
            AvailabilityWindow.coordinator_id == coord_id,
            AvailabilityWindow.day == d,
            ~((AvailabilityWindow.end_time <= start_t) | (AvailabilityWindow.start_time >= end_t)),
        )
        .all()
    )
    slots_deleted = (
        db.query(TimeSlot)
        .filter(
            TimeSlot.coordinator_id == coord_id,
            TimeSlot.day == d,
            TimeSlot.start_time >= start_t,
            TimeSlot.start_time < end_t,
            TimeSlot.is_booked == False,
        )
        .delete(synchronize_session=False)
    )
    wins_deleted = 0
    for w in overlapping:
        db.delete(w)
        wins_deleted += 1

    # Crear nueva ventana
    av = AvailabilityWindow(
        coordinator_id=coord_id,
        day=d,
        start_time=start_t,
        end_time=end_t,
        slot_minutes=body.slot_minutes,
    )
    db.add(av)
    db.flush()

    # Generar slots
    created = 0
    step = timedelta(minutes=body.slot_minutes)
    cur = datetime.combine(d, start_t)
    end_dt = datetime.combine(d, end_t)
    while (cur + step) <= end_dt:
        db.add(TimeSlot(
            coordinator_id=coord_id,
            day=d,
            start_time=cur.time(),
            end_time=(cur + step).time(),
            is_booked=False,
        ))
        created += 1
        cur += step
    db.commit()

    try:
        from itcj2.core.sockets import get_socketio
        sio = get_socketio()
        sio.emit("slots_window_changed", {"day": str(d)}, to=f"day:{str(d)}", namespace="/slots")
    except Exception:
        logger.exception("Failed to emit slots_window_changed")

    return {"ok": True, "windows_deleted": wins_deleted, "slots_deleted": slots_deleted, "slots_created": created}


# ==================== DELETE /day-config ====================

@router.delete("/day-config")
def delete_day_range(
    body: DeleteDayRangeBody,
    user: dict = DeletePerm,
    db: DbSession = None,
):
    """Borra el rango [start, end) de slots en un día."""
    coord_id = require_coordinator(int(user["sub"]), db)
    d = _parse_day(body.day)

    _, enabled = _get_active_period_and_days()
    if d not in enabled:
        raise HTTPException(status_code=400, detail="day_not_allowed")

    if date.today() >= d:
        raise HTTPException(status_code=400, detail="cannot_modify_today_or_past")

    start_t = parse_time_str(body.start)
    end_t = parse_time_str(body.end)
    if not start_t or not end_t:
        raise HTTPException(status_code=400, detail="invalid_time_format")
    if end_t <= start_t:
        raise HTTPException(status_code=400, detail="invalid_time_range")

    booked_cnt = (
        db.query(TimeSlot.id)
        .filter(
            TimeSlot.coordinator_id == coord_id,
            TimeSlot.day == d,
            TimeSlot.start_time >= start_t,
            TimeSlot.start_time < end_t,
            TimeSlot.is_booked == True,
        )
        .count()
    )
    if booked_cnt > 0:
        raise HTTPException(status_code=409, detail={"error": "overlap_booked_slots_exist", "booked_count": booked_cnt})

    slots_deleted = (
        db.query(TimeSlot)
        .filter(
            TimeSlot.coordinator_id == coord_id,
            TimeSlot.day == d,
            TimeSlot.start_time >= start_t,
            TimeSlot.start_time < end_t,
            TimeSlot.is_booked == False,
        )
        .delete(synchronize_session=False)
    )

    win_stats = split_or_delete_windows(coord_id, d, start_t, end_t, db)
    db.commit()

    try:
        from itcj2.core.sockets import get_socketio
        sio = get_socketio()
        sio.emit("slots_window_changed", {"day": str(d)}, to=f"day:{str(d)}", namespace="/slots")
    except Exception:
        logger.exception("Failed to emit slots_window_changed")

    return {"ok": True, "day": str(d), "slots_deleted": slots_deleted, **win_stats}
