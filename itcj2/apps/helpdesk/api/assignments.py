"""
Assignments API v2 — 7 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/assignments.py
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from itcj2.dependencies import DbSession, require_perms, require_roles
from itcj2.apps.helpdesk.schemas.assignments import (
    AssignTicketRequest,
    ReassignTicketRequest,
)

router = APIRouter(tags=["helpdesk-assignments"])
logger = logging.getLogger(__name__)


@router.post("", status_code=201)
async def assign_ticket(
    body: AssignTicketRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.assignments.api.assign"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import assignment_service

    user_id = int(user["sub"])

    if not body.assigned_to_user_id and not body.assigned_to_team:
        raise HTTPException(400, detail={
            "error": "missing_assignment_target",
            "message": "Debe proporcionar assigned_to_user_id o assigned_to_team",
        })

    assignment = assignment_service.assign_ticket(
        db,
        ticket_id=body.ticket_id,
        assigned_by_id=user_id,
        assigned_to_user_id=body.assigned_to_user_id,
        assigned_to_team=body.assigned_to_team,
        reason=body.reason,
    )

    logger.info(f"Ticket {body.ticket_id} asignado por usuario {user_id}")

    ticket = assignment.ticket
    if ticket.assigned_to_user_id:
        from itcj2.apps.helpdesk.services.notification_helper import HelpdeskNotificationHelper
        try:
            HelpdeskNotificationHelper.notify_ticket_assigned(db, ticket, ticket.assigned_to)
            db.commit()
        except Exception as notif_error:
            logger.error(f"Error al enviar notificación de asignación: {notif_error}")

        try:
            from itcj2.sockets.helpdesk import broadcast_ticket_assigned
            await broadcast_ticket_assigned(
                ticket.id,
                ticket.assigned_to_user_id,
                ticket.area,
                {
                    "ticket_id": ticket.id,
                    "ticket_number": ticket.ticket_number,
                    "title": ticket.title,
                    "assigned_to_id": ticket.assigned_to_user_id,
                    "assigned_to_name": ticket.assigned_to.full_name if ticket.assigned_to else None,
                    "area": ticket.area,
                    "priority": ticket.priority,
                },
                department_id=ticket.requester_department_id,
            )
        except Exception as ws_err:
            logger.warning(f"WS broadcast ticket_assigned error: {ws_err}")

    return {"message": "Ticket asignado exitosamente", "assignment": assignment.to_dict()}


@router.post("/{ticket_id}/reassign")
async def reassign_ticket(
    ticket_id: int,
    body: ReassignTicketRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.assignments.api.reassign"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import assignment_service

    user_id = int(user["sub"])

    if not body.assigned_to_user_id and not body.assigned_to_team:
        raise HTTPException(400, detail={
            "error": "missing_assignment_target",
            "message": "Debe proporcionar assigned_to_user_id o assigned_to_team",
        })

    assignment = assignment_service.reassign_ticket(
        db,
        ticket_id=ticket_id,
        reassigned_by_id=user_id,
        assigned_to_user_id=body.assigned_to_user_id,
        assigned_to_team=body.assigned_to_team,
        reason=body.reason,
    )

    logger.info(f"Ticket {ticket_id} reasignado por usuario {user_id}")

    from itcj2.apps.helpdesk.services.notification_helper import HelpdeskNotificationHelper
    from itcj2.core.models.user import User

    ticket = assignment.ticket
    previous_user = None
    try:
        prev_assignments = ticket.assignments.filter_by(is_active=False).order_by(db.desc("created_at")).first()
        if prev_assignments and prev_assignments.assigned_to_user_id:
            previous_user = db.get(User, prev_assignments.assigned_to_user_id)
        if ticket.assigned_to_user_id:
            HelpdeskNotificationHelper.notify_ticket_reassigned(db, ticket, ticket.assigned_to, previous_user)
        db.commit()
    except Exception as notif_error:
        logger.error(f"Error al enviar notificación de reasignación: {notif_error}")

    if ticket.assigned_to_user_id:
        try:
            from itcj2.sockets.helpdesk import broadcast_ticket_reassigned
            prev_id = previous_user.id if previous_user else None
            await broadcast_ticket_reassigned(
                ticket.id,
                ticket.assigned_to_user_id,
                prev_id,
                ticket.area,
                {
                    "ticket_id": ticket.id,
                    "ticket_number": ticket.ticket_number,
                    "title": ticket.title,
                    "new_assigned_id": ticket.assigned_to_user_id,
                    "new_assigned_name": ticket.assigned_to.full_name if ticket.assigned_to else None,
                    "prev_assigned_id": prev_id,
                    "prev_assigned_name": previous_user.full_name if previous_user else None,
                    "area": ticket.area,
                },
                department_id=ticket.requester_department_id,
            )
        except Exception as ws_err:
            logger.warning(f"WS broadcast ticket_reassigned error: {ws_err}")

    return {"message": "Ticket reasignado exitosamente", "assignment": assignment.to_dict()}


@router.post("/{ticket_id}/self-assign")
async def self_assign_ticket(
    ticket_id: int,
    user: dict = require_roles("helpdesk", ["tech_desarrollo", "tech_soporte", "admin"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import assignment_service

    user_id = int(user["sub"])

    assignment = assignment_service.self_assign_ticket(
        db,
        ticket_id=ticket_id,
        technician_id=user_id,
    )

    logger.info(f"Técnico {user_id} se auto-asignó el ticket {ticket_id}")

    from itcj2.apps.helpdesk.services.notification_helper import HelpdeskNotificationHelper
    from itcj2.core.models.user import User

    ticket = assignment.ticket
    technician = None
    try:
        technician = db.get(User, user_id)
        if technician:
            HelpdeskNotificationHelper.notify_ticket_self_assigned(db, ticket, technician)
        db.commit()
    except Exception as notif_error:
        logger.error(f"Error al enviar notificación de auto-asignación: {notif_error}")

    try:
        from itcj2.sockets.helpdesk import broadcast_ticket_self_assigned
        await broadcast_ticket_self_assigned(
            ticket.id,
            ticket.area,
            {
                "ticket_id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "title": ticket.title,
                "technician_id": user_id,
                "technician_name": technician.full_name if technician else None,
                "area": ticket.area,
            },
        )
    except Exception as ws_err:
        logger.warning(f"WS broadcast ticket_self_assigned error: {ws_err}")

    return {"message": "Te has asignado el ticket exitosamente", "assignment": assignment.to_dict()}


@router.get("/{ticket_id}/history")
def get_assignment_history(
    ticket_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.all"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import assignment_service

    history = assignment_service.get_assignment_history(db, ticket_id)
    return {"ticket_id": ticket_id, "history": history}


@router.get("/team/{team_name}")
def get_team_tickets(
    team_name: str,
    request: Request,
    user: dict = require_roles("helpdesk", ["tech_desarrollo", "tech_soporte", "admin"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import assignment_service

    user_id = int(user["sub"])
    include_details = request.query_params.get("include_details", "false").lower() == "true"

    tickets = assignment_service.get_team_tickets(
        db,
        team_name=team_name,
        technician_id=user_id,
    )

    tickets_data = []
    for ticket in tickets:
        if include_details:
            tickets_data.append(ticket.to_dict(include_relations=True))
        else:
            tickets_data.append({
                "id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "title": ticket.title,
                "area": ticket.area,
                "priority": ticket.priority,
                "status": ticket.status,
                "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
                "requester": {
                    "id": ticket.requester.id,
                    "name": ticket.requester.full_name,
                } if ticket.requester else None,
            })

    return {"team": team_name, "count": len(tickets_data), "tickets": tickets_data}


@router.get("/technicians/{area}")
def get_available_technicians(
    area: str,
    user: dict = require_perms("helpdesk", ["helpdesk.assignments.api.assign"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import assignment_service

    if area not in ("DESARROLLO", "SOPORTE"):
        raise HTTPException(400, detail={"error": "invalid_area", "message": "El área debe ser DESARROLLO o SOPORTE"})

    technicians = assignment_service.get_technicians_by_area(db, area)

    from itcj2.apps.helpdesk.models import Ticket
    technicians_data = []
    for tech in technicians:
        active_tickets_count = db.query(Ticket).filter(
            Ticket.assigned_to_user_id == tech.id,
            Ticket.status.in_(["ASSIGNED", "IN_PROGRESS"]),
        ).count()
        technicians_data.append({
            "id": tech.id,
            "name": tech.full_name,
            "username": tech.username,
            "active_tickets": active_tickets_count,
        })

    technicians_data.sort(key=lambda x: x["active_tickets"])
    return {"area": area, "technicians": technicians_data}


@router.get("/stats")
def get_assignment_stats(
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.all"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import Ticket

    unassigned = db.query(Ticket).filter_by(status="PENDING").count()
    team_assigned = db.query(Ticket).filter(
        Ticket.assigned_to_team.isnot(None),
        Ticket.assigned_to_user_id.is_(None),
        Ticket.status.in_(["ASSIGNED", "IN_PROGRESS"]),
    ).count()
    in_progress_desarrollo = db.query(Ticket).filter(
        Ticket.area == "DESARROLLO",
        Ticket.status.in_(["ASSIGNED", "IN_PROGRESS"]),
    ).count()
    in_progress_soporte = db.query(Ticket).filter(
        Ticket.area == "SOPORTE",
        Ticket.status.in_(["ASSIGNED", "IN_PROGRESS"]),
    ).count()
    urgent_unassigned = db.query(Ticket).filter(
        Ticket.priority == "URGENTE", Ticket.status == "PENDING"
    ).count()

    return {
        "unassigned": unassigned,
        "team_assigned": team_assigned,
        "urgent_unassigned": urgent_unassigned,
        "in_progress": {"desarrollo": in_progress_desarrollo, "soporte": in_progress_soporte},
    }
