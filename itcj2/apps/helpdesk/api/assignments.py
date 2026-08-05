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
    user: dict = require_perms("helpdesk", [
        "helpdesk.tickets.api.read.own",
        "helpdesk.tickets.api.read.all",
        "helpdesk.tickets.api.read.subtree",
    ]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import assignment_service
    from itcj2.apps.helpdesk.services import ticket_service

    user_id = int(user["sub"])
    # `department_head` tiene `.read.all` por ROL (DML), pero eso no implica
    # que pueda ver CUALQUIER ticket: la autorización fina la sigue haciendo
    # `can_user_view_ticket` (mismo patrón que GET /tickets/{id}). Sin esto,
    # el historial de asignaciones —quién, cuándo, con qué notas— se fugaba a
    # cualquier rama del organigrama.
    ticket_service.get_ticket_by_id(db, ticket_id, user_id, check_permissions=True)

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

    from itcj2.apps.helpdesk.utils.catalog_cache import get_area_codes
    valid_areas = get_area_codes(db, active_only=False)
    if area not in valid_areas:
        raise HTTPException(400, detail={"error": "invalid_area", "message": f"El área debe ser una de: {sorted(valid_areas)}"})

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
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])

    # `.read.all` NO implica acceso total: `department_head` lo tiene por rol
    # (DML) pero estos contadores son del INSTITUTO completo. Mismo criterio de
    # acceso total que `ticket_service.list_tickets`: admin / técnicos /
    # secretary_comp_center ven todo; el resto se acota a su scope de lectura
    # (subárbol por procedencia + su departamento primario).
    has_full_access = (
        "admin" in user_roles
        or "tech_desarrollo" in user_roles
        or "tech_soporte" in user_roles
        or user_id in secretary_comp_center
    )

    dept_ids = None
    if not has_full_access:
        from itcj2.core.services.departments_service import get_primary_user_department
        from itcj2.core.services.scope_service import subtree_scope_for

        dept_ids = subtree_scope_for(db, user_id, "helpdesk", "helpdesk.tickets.api.read.subtree")
        primary_dept = get_primary_user_department(db, user_id)
        if primary_dept:
            dept_ids = dept_ids | {primary_dept.id}

    def _scoped(query):
        if dept_ids is not None:
            # Vacío -> ningún departamento visible, no "sin filtro".
            query = query.filter(Ticket.requester_department_id.in_(dept_ids or {-1}))
        return query

    unassigned = _scoped(db.query(Ticket).filter_by(status="PENDING")).count()
    team_assigned = _scoped(db.query(Ticket).filter(
        Ticket.assigned_to_team.isnot(None),
        Ticket.assigned_to_user_id.is_(None),
        Ticket.status.in_(["ASSIGNED", "IN_PROGRESS"]),
    )).count()
    in_progress_desarrollo = _scoped(db.query(Ticket).filter(
        Ticket.area == "DESARROLLO",
        Ticket.status.in_(["ASSIGNED", "IN_PROGRESS"]),
    )).count()
    in_progress_soporte = _scoped(db.query(Ticket).filter(
        Ticket.area == "SOPORTE",
        Ticket.status.in_(["ASSIGNED", "IN_PROGRESS"]),
    )).count()
    urgent_unassigned = _scoped(db.query(Ticket).filter(
        Ticket.priority == "URGENTE", Ticket.status == "PENDING"
    )).count()

    return {
        "unassigned": unassigned,
        "team_assigned": team_assigned,
        "urgent_unassigned": urgent_unassigned,
        "in_progress": {"desarrollo": in_progress_desarrollo, "soporte": in_progress_soporte},
    }
