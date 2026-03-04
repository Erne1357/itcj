"""
Stats API v2 — 2 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/stats.py
"""
import logging
from datetime import datetime, time

from fastapi import APIRouter, HTTPException
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["helpdesk-stats"])
logger = logging.getLogger(__name__)


@router.get("/department/{department_id}")
def get_department_stats(
    department_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj2.apps.helpdesk.models.ticket import Ticket

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])

    can_view = False
    if "admin" in user_roles or user_id in secretary_comp_center:
        can_view = True
    elif "department_head" in user_roles:
        from itcj2.core.models.position import UserPosition
        user_position = db.query(UserPosition).filter_by(user_id=user_id, is_active=True).first()
        if user_position and user_position.position:
            can_view = user_position.position.department_id == department_id

    if not can_view:
        raise HTTPException(403, detail={"error": "forbidden", "message": "No tienes permiso para ver las estadísticas de este departamento"})

    query = db.query(Ticket).filter_by(requester_department_id=department_id)

    active_count = query.filter(Ticket.status.in_(["PENDING", "ASSIGNED", "IN_PROGRESS"])).count()
    resolved_count = query.filter(Ticket.status.in_(["RESOLVED_SUCCESS", "RESOLVED_FAILED", "CLOSED"])).count()

    resolved_tickets = query.filter(Ticket.resolved_at.isnot(None), Ticket.created_at.isnot(None)).all()
    avg_hours = 0
    if resolved_tickets:
        total_hours = sum((t.resolved_at - t.created_at).total_seconds() / 3600 for t in resolved_tickets)
        avg_hours = round(total_hours / len(resolved_tickets), 1)

    rated_tickets = query.filter(Ticket.rating_attention.isnot(None)).all()
    satisfaction_percent = 0
    if rated_tickets:
        avg_rating = sum(t.rating_attention for t in rated_tickets) / len(rated_tickets)
        satisfaction_percent = round((avg_rating / 5) * 100, 1)

    total_count = query.count()

    return {
        "success": True,
        "data": {
            "department_id": department_id,
            "total_tickets": total_count,
            "active_tickets": active_count,
            "resolved_tickets": resolved_count,
            "avg_resolution_hours": avg_hours,
            "satisfaction_percent": satisfaction_percent,
            "rated_tickets_count": len(rated_tickets),
        },
    }


@router.get("/technician")
def get_technician_stats(
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.resolve"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.ticket import Ticket

    user_id = int(user["sub"])

    assigned_count = db.query(Ticket).filter_by(assigned_to_user_id=user_id, status="ASSIGNED").count()
    in_progress_count = db.query(Ticket).filter_by(assigned_to_user_id=user_id, status="IN_PROGRESS").count()
    resolved_count = db.query(Ticket).filter_by(assigned_to_user_id=user_id).filter(
        Ticket.status.in_(["RESOLVED_SUCCESS", "RESOLVED_FAILED", "CLOSED"])
    ).count()

    resolved_tickets = db.query(Ticket).filter_by(assigned_to_user_id=user_id).filter(
        Ticket.resolved_at.isnot(None), Ticket.created_at.isnot(None)
    ).all()

    avg_hours = 0
    if resolved_tickets:
        total_hours = sum((t.resolved_at - t.created_at).total_seconds() / 3600 for t in resolved_tickets)
        avg_hours = round(total_hours / len(resolved_tickets), 1)

    rated_tickets = db.query(Ticket).filter_by(assigned_to_user_id=user_id).filter(Ticket.rating_attention.isnot(None)).all()
    satisfaction_percent = 0
    if rated_tickets:
        avg_rating = sum(t.rating_attention for t in rated_tickets) / len(rated_tickets)
        satisfaction_percent = round((avg_rating / 5) * 100, 1)

    today_start = datetime.combine(datetime.today(), time.min)
    resolved_today_count = db.query(Ticket).filter_by(assigned_to_user_id=user_id).filter(
        Ticket.resolved_at >= today_start,
        Ticket.status.in_(["RESOLVED_SUCCESS", "RESOLVED_FAILED", "CLOSED"]),
    ).count()

    return {
        "success": True,
        "data": {
            "assigned_count": assigned_count,
            "in_progress_count": in_progress_count,
            "resolved_count": resolved_count,
            "resolved_today_count": resolved_today_count,
            "avg_resolution_hours": avg_hours,
            "satisfaction_percent": satisfaction_percent,
        },
    }
