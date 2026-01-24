# routes/api/coord/dashboard.py
"""
Endpoints de dashboard para coordinadores.

Incluye:
- get_shared_coordinators: Lista coordinadores que comparten programas
- coord_dashboard_summary: Resumen del dashboard
"""
from __future__ import annotations

from flask import Blueprint, jsonify
from sqlalchemy import func

from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.appointment import Appointment
from itcj.apps.agendatec.models.availability_window import AvailabilityWindow
from itcj.apps.agendatec.models.request import Request
from itcj.apps.agendatec.models.time_slot import TimeSlot
from itcj.core.models.coordinator import Coordinator
from itcj.core.models.program_coordinator import ProgramCoordinator
from itcj.core.models.user import User
from itcj.core.services import period_service
from itcj.core.utils.decorators import api_app_required, api_auth_required

from .helpers import get_current_coordinator_id, get_coord_program_ids

coord_dashboard_bp = Blueprint("coord_dashboard", __name__)


@coord_dashboard_bp.get("/shared-coordinators")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.coord_dashboard.api.read"])
def get_shared_coordinators():
    """
    Devuelve la lista de coordinadores que comparten al menos un programa
    con el coordinador actual.

    Returns:
        JSON con has_multiple_coordinators, coordinators y current_coordinator_id
    """
    coord_id = get_current_coordinator_id()
    if not coord_id:
        return jsonify({"error": "coordinator_not_found"}), 404

    # Obtener programas del coordinador
    prog_ids = get_coord_program_ids(coord_id)

    # Obtener todos los coordinadores que comparten estos programas
    shared_coords = (
        db.session.query(Coordinator, User)
        .join(User, User.id == Coordinator.user_id)
        .join(ProgramCoordinator, ProgramCoordinator.coordinator_id == Coordinator.id)
        .filter(ProgramCoordinator.program_id.in_(prog_ids))
        .distinct()
        .all()
    )

    # Formatear respuesta
    coordinators = [{
        "id": c.id,
        "name": u.full_name,
        "is_me": c.id == coord_id
    } for c, u in shared_coords]

    # Determinar si hay múltiples coordinadores
    has_multiple = len(coordinators) > 1

    return jsonify({
        "has_multiple_coordinators": has_multiple,
        "coordinators": coordinators,
        "current_coordinator_id": coord_id
    })


@coord_dashboard_bp.get("/dashboard")
@api_auth_required
@api_app_required(app_key="agendatec", perms=["agendatec.coord_dashboard.api.read"])
def coord_dashboard_summary():
    """
    Resumen del dashboard del coordinador.

    Returns:
        JSON con period, days_allowed, appointments, drops y missing_slots
    """
    coord_id = get_current_coordinator_id()
    if not coord_id:
        return jsonify({"error": "coordinator_not_found"}), 404

    # Obtener días habilitados del período activo
    period = period_service.get_active_period()
    if not period:
        return jsonify({"error": "no_active_period"}), 503

    enabled_days = set(period_service.get_enabled_days(period.id))

    # Obtener programas del coordinador para visibilidad compartida
    prog_ids = get_coord_program_ids(coord_id)

    # Citas de TODOS los coordinadores que comparten programas
    ap_base = (
        db.session.query(Appointment.id)
        .join(TimeSlot, TimeSlot.id == Appointment.slot_id)
        .filter(Appointment.program_id.in_(prog_ids),
                TimeSlot.day.in_(enabled_days))
    )
    ap_total = ap_base.count()

    ap_pending = (
        db.session.query(func.count(Request.id))
        .join(Appointment, Appointment.request_id == Request.id)
        .join(TimeSlot, TimeSlot.id == Appointment.slot_id)
        .filter(Appointment.program_id.in_(prog_ids),
                TimeSlot.day.in_(enabled_days),
                Request.status == "PENDING")
    ).scalar() or 0

    # Drops de los programas del coordinador
    drop_q = (
        db.session.query(Request.id)
        .filter(Request.type == "DROP",
                Request.program_id.in_(prog_ids),
                Request.period_id == period.id)
    )
    drops_total = drop_q.count()
    drops_pending = (
        db.session.query(func.count(Request.id))
        .filter(Request.type == "DROP",
                Request.program_id.in_(prog_ids),
                Request.period_id == period.id,
                Request.status == "PENDING")
    ).scalar() or 0

    # Recordatorios: días habilitados SIN ventanas configuradas
    missing = []
    for d in sorted(enabled_days):
        has_win = (
            db.session.query(AvailabilityWindow.id)
            .filter(AvailabilityWindow.coordinator_id == coord_id,
                    AvailabilityWindow.day == d)
            .first()
        )
        if not has_win:
            missing.append(str(d))

    # Información del período activo
    period_info = {
        "id": period.id,
        "name": period.name,
        "start_date": period.start_date.isoformat(),
        "end_date": period.end_date.isoformat()
    }

    return jsonify({
        "period": period_info,
        "days_allowed": [str(x) for x in sorted(enabled_days)],
        "appointments": {"total": ap_total, "pending": ap_pending},
        "drops": {"total": drops_total, "pending": drops_pending},
        "missing_slots": missing
    })
