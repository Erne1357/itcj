"""
Availability API v2 — Slots y ventanas de disponibilidad.
Fuente: itcj/apps/agendatec/routes/api/availability.py
"""
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from itcj2.dependencies import DbSession, require_perms, require_roles
from itcj2.apps.agendatec.helpers import now_app, parse_date_str, TEMP_TEST_GATE_check_student  # TEMP_TEST_GATE

from itcj2.apps.agendatec.models.availability_window import AvailabilityWindow
from itcj2.apps.agendatec.models.time_slot import TimeSlot
from itcj2.core.models.coordinator import Coordinator
from itcj2.core.models.program import Program
from itcj2.core.models.program_coordinator import ProgramCoordinator
from itcj2.core.models.user import User
from itcj2.core.services import period_service

router = APIRouter(tags=["agendatec-availability"])
logger = logging.getLogger(__name__)

def _get_enabled_days_for_active_period(db) -> set[date]:
    period = period_service.get_active_period(db)
    if not period:
        return set()
    return set(period_service.get_enabled_days(db, period.id))


def _require_allowed_day(d: date, db) -> None:
    """Lanza 400 si el día no está habilitado en el período activo."""
    period = period_service.get_active_period(db)
    if not period:
        raise HTTPException(status_code=503, detail="no_active_period")
    enabled = set(period_service.get_enabled_days(db, period.id))
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
    u = db.get(User, uid)
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
    TEMP_TEST_GATE_check_student(user, db)  # TEMP_TEST_GATE
    if day:
        d = parse_date_str(day)
        if not d:
            raise HTTPException(status_code=400, detail="invalid_day_format")
    else:
        d = date.today()

    prog = db.get(Program, program_id)
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

    from itcj2.apps.agendatec.models import TimeSlotProgram

    q = (
        db.query(TimeSlot)
        # El scope del rango: el coordinador pudo limitarlo a ciertas carreras.
        # `coordinator_id.in_(coor_ids)` se conserva porque TimeSlotProgram por
        # sí solo no garantiza que el coordinador siga asignado a esa carrera.
        .join(TimeSlotProgram, TimeSlotProgram.slot_id == TimeSlot.id)
        .filter(
            TimeSlotProgram.program_id == program_id,
            TimeSlot.coordinator_id.in_(coor_ids),
            TimeSlot.day == d,
            TimeSlot.is_booked == False,
        )
    )

    # No ofrecer lo que ya pasó: antes el alumno solo se enteraba al confirmar,
    # con un 400 slot_time_passed tras haber completado todo el wizard.
    now_local = now_app()
    if d == now_local.date():
        q = q.filter(TimeSlot.start_time > now_local.time())

    slots = q.order_by(TimeSlot.start_time.asc()).all()

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


# ==================== Endpoints retirados ====================
# POST /windows y POST /generate-slots quedaron retirados (410).
#
# `generate_slots` iteraba las AvailabilityWindow del día SIN filtrar por
# coordinador, así que cualquier portador de agendatec.slots.api.create
# generaba slots de TODOS los coordinadores del sistema. Y su comprobación de
# duplicado solo comparaba `start_time ==`, sin detectar solapes: corrido
# después de un split, recreaba la grilla vieja encima de la nueva.
#
# `create_availability_window` creaba la ventana pero NO sus slots ni su scope
# por carrera, dejando configuraciones a medias.
#
# Ningún frontend los llamaba (verificado por grep sobre .js y .html). La
# generación de slots vive ahora en SlotService, vía POST /coord/day-config,
# que es el único camino que aplica el scope y el split.

_GONE = (
    "Endpoint retirado. La generación de horarios vive en "
    "POST /api/agendatec/v2/coord/day-config, el único camino que aplica el "
    "scope por carrera y la re-división de rangos."
)


@router.post("/windows")
def create_availability_window_gone():
    raise HTTPException(status_code=410, detail=_GONE)


@router.post("/generate-slots")
def generate_slots_gone():
    raise HTTPException(status_code=410, detail=_GONE)


# ==================== GET /windows ====================

@router.get("/windows")
def list_my_windows(
    day: Optional[str] = Query(None, description="Fecha YYYY-MM-DD"),
    coordinator_id: Optional[int] = Query(None),
    user: dict = require_perms("agendatec", ["agendatec.slots.api.read"]),
    db: DbSession = None,
):
    """Lista ventanas de disponibilidad del coordinador para un día."""
    TEMP_TEST_GATE_check_student(user, db)  # TEMP_TEST_GATE
    if day:
        d = parse_date_str(day)
        if not d:
            raise HTTPException(status_code=400, detail="invalid_day_format")
    else:
        d = date.today()

    _require_allowed_day(d, db)

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
