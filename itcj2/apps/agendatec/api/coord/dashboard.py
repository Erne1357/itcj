"""
Coord Dashboard API v2 — Dashboard del coordinador.
Fuente: itcj/apps/agendatec/routes/api/coord/dashboard.py
"""
import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import func

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.agendatec.helpers import require_coordinator, get_coord_program_ids
from itcj2.apps.agendatec.models.appointment import Appointment
from itcj2.apps.agendatec.models.availability_window import AvailabilityWindow
from itcj2.apps.agendatec.models.request import Request
from itcj2.apps.agendatec.models.time_slot import TimeSlot
from itcj2.core.models.coordinator import Coordinator
from itcj2.core.models.program_coordinator import ProgramCoordinator
from itcj2.core.models.user import User
from itcj2.core.services import period_service

router = APIRouter(tags=["agendatec-coord-dashboard"])
logger = logging.getLogger(__name__)

DashPerm = require_perms("agendatec", ["agendatec.coord_dashboard.api.read"])


# ==================== GET /shared-coordinators ====================

@router.get("/shared-coordinators")
def get_shared_coordinators(
    user: dict = DashPerm,
    db: DbSession = None,
):
    """Lista coordinadores que comparten al menos un programa con el coordinador actual."""
    coord_id = require_coordinator(int(user["sub"]), db)
    prog_ids = get_coord_program_ids(coord_id, db)

    shared = (
        db.query(Coordinator, User)
        .join(User, User.id == Coordinator.user_id)
        .join(ProgramCoordinator, ProgramCoordinator.coordinator_id == Coordinator.id)
        .filter(ProgramCoordinator.program_id.in_(prog_ids))
        .distinct()
        .all()
    )

    coordinators = [
        {"id": c.id, "name": u.full_name, "is_me": c.id == coord_id}
        for c, u in shared
    ]

    return {
        "has_multiple_coordinators": len(coordinators) > 1,
        "coordinators": coordinators,
        "current_coordinator_id": coord_id,
    }


# ==================== GET /dashboard ====================

@router.get("/dashboard")
def coord_dashboard_summary(
    user: dict = DashPerm,
    db: DbSession = None,
):
    """Resumen del dashboard del coordinador."""
    coord_id = require_coordinator(int(user["sub"]), db)

    period = period_service.get_active_period(db)
    if not period:
        raise HTTPException(status_code=503, detail="no_active_period")

    enabled_days = set(period_service.get_enabled_days(db, period.id))
    prog_ids = get_coord_program_ids(coord_id, db)

    ap_total = (
        db.query(Appointment.id)
        .join(TimeSlot, TimeSlot.id == Appointment.slot_id)
        .filter(Appointment.program_id.in_(prog_ids), TimeSlot.day.in_(enabled_days))
        .count()
    )
    ap_pending = (
        db.query(func.count(Request.id))
        .join(Appointment, Appointment.request_id == Request.id)
        .join(TimeSlot, TimeSlot.id == Appointment.slot_id)
        .filter(
            Appointment.program_id.in_(prog_ids),
            TimeSlot.day.in_(enabled_days),
            Request.status == "PENDING",
        )
        .scalar()
        or 0
    )

    drops_total = (
        db.query(Request.id)
        .filter(Request.type == "DROP", Request.program_id.in_(prog_ids), Request.period_id == period.id)
        .count()
    )
    drops_pending = (
        db.query(func.count(Request.id))
        .filter(
            Request.type == "DROP",
            Request.program_id.in_(prog_ids),
            Request.period_id == period.id,
            Request.status == "PENDING",
        )
        .scalar()
        or 0
    )

    missing = [
        str(d)
        for d in sorted(enabled_days)
        if not db.query(AvailabilityWindow.id)
        .filter(AvailabilityWindow.coordinator_id == coord_id, AvailabilityWindow.day == d)
        .first()
    ]

    return {
        "period": {
            "id": period.id,
            "name": period.name,
            "start_date": period.start_date.isoformat(),
            "end_date": period.end_date.isoformat(),
        },
        "days_allowed": [str(x) for x in sorted(enabled_days)],
        "appointments": {"total": ap_total, "pending": ap_pending},
        "drops": {"total": drops_total, "pending": drops_pending},
        "missing_slots": missing,
    }
