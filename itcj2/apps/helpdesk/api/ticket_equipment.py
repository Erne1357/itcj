"""
Ticket Equipment API v2 — 5 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/tickets/equipment.py
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from itcj2.dependencies import DbSession, require_perms
from itcj2.utils import flask_service_call
from itcj2.apps.helpdesk.schemas.tickets import AddEquipmentRequest, ReplaceEquipmentRequest

router = APIRouter(tags=["helpdesk-equipment"])
logger = logging.getLogger(__name__)


@router.post("/{ticket_id}/equipment")
def add_equipment_to_ticket(
    ticket_id: int,
    body: AddEquipmentRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj.apps.helpdesk.services import ticket_service
    from itcj.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    ticket = flask_service_call(ticket_service.get_ticket_by_id, ticket_id, user_id, check_permissions=True)

    user_roles = user_roles_in_app(user_id, "helpdesk")
    if ticket.requester_id != user_id and ticket.assigned_to_user_id != user_id and "admin" not in user_roles:
        raise HTTPException(403, detail={"error": "forbidden", "message": "No tienes permiso para modificar los equipos de este ticket"})

    from itcj.apps.helpdesk.services.ticket_inventory_service import TicketInventoryService
    try:
        added = TicketInventoryService.add_items_to_ticket(ticket_id, body.item_ids)
    except ValueError as e:
        raise HTTPException(400, detail={"error": "invalid_equipment", "message": str(e)})

    logger.info(f"{len(added)} equipos agregados al ticket {ticket_id}")
    return {"message": f"{len(added)} equipos agregados exitosamente", "added_items": [item.to_dict() for item in added]}


@router.delete("/{ticket_id}/equipment/{item_id}")
def remove_equipment_from_ticket(
    ticket_id: int,
    item_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj.apps.helpdesk.services import ticket_service
    from itcj.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    ticket = flask_service_call(ticket_service.get_ticket_by_id, ticket_id, user_id, check_permissions=True)

    user_roles = user_roles_in_app(user_id, "helpdesk")
    if ticket.requester_id != user_id and ticket.assigned_to_user_id != user_id and "admin" not in user_roles:
        raise HTTPException(403, detail={"error": "forbidden", "message": "No tienes permiso para modificar los equipos de este ticket"})

    from itcj.apps.helpdesk.services.ticket_inventory_service import TicketInventoryService
    try:
        TicketInventoryService.remove_item_from_ticket(ticket_id, item_id)
    except ValueError as e:
        raise HTTPException(400, detail={"error": "invalid_operation", "message": str(e)})

    logger.info(f"Equipo {item_id} removido del ticket {ticket_id}")
    return {"message": "Equipo removido exitosamente"}


@router.put("/{ticket_id}/equipment")
def replace_ticket_equipment(
    ticket_id: int,
    body: ReplaceEquipmentRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj.apps.helpdesk.services import ticket_service
    from itcj.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    ticket = flask_service_call(ticket_service.get_ticket_by_id, ticket_id, user_id, check_permissions=True)

    user_roles = user_roles_in_app(user_id, "helpdesk")
    if ticket.requester_id != user_id and ticket.assigned_to_user_id != user_id and "admin" not in user_roles:
        raise HTTPException(403, detail={"error": "forbidden", "message": "No tienes permiso para modificar los equipos de este ticket"})

    from itcj.apps.helpdesk.services.ticket_inventory_service import TicketInventoryService
    try:
        replaced = TicketInventoryService.replace_ticket_items(ticket_id, body.item_ids)
    except ValueError as e:
        raise HTTPException(400, detail={"error": "invalid_equipment", "message": str(e)})

    logger.info(f"Equipos del ticket {ticket_id} reemplazados: {len(replaced)} nuevos")
    return {"message": f"Equipos reemplazados exitosamente: {len(replaced)} nuevos", "items": [item.to_dict() for item in replaced]}


@router.get("/{ticket_id}/equipment")
def get_ticket_equipment(
    ticket_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj.apps.helpdesk.services import ticket_service

    user_id = int(user["sub"])
    ticket = flask_service_call(ticket_service.get_ticket_by_id, ticket_id, user_id, check_permissions=True)

    equipment = [item.to_dict(include_relations=True) for item in ticket.inventory_items]
    return {"ticket_id": ticket_id, "equipment": equipment, "count": len(equipment)}


@router.get("/equipment/{item_id}")
def get_tickets_by_equipment(
    item_id: int,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj.apps.helpdesk.models import InventoryItem, Ticket, TicketInventoryItem
    from itcj.core.extensions import db as flask_db
    from sqlalchemy import or_

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(user_id, "helpdesk")

    item = InventoryItem.query.get(item_id)
    if not item or not item.is_active:
        raise HTTPException(404, detail={"error": "not_found", "message": "Equipo no encontrado"})

    secretary_comp_center = _get_users_with_position(["secretary_comp_center"])

    if "admin" not in user_roles and user_id not in secretary_comp_center:
        if item.assigned_to_user_id != user_id:
            from itcj.core.services.departments_service import get_user_department
            user_dept = get_user_department(user_id)
            if not user_dept or user_dept.id != item.department_id:
                if "technician" not in user_roles and "department_head" not in user_roles:
                    raise HTTPException(403, detail={"error": "forbidden", "message": "No tienes permiso para ver los tickets de este equipo"})

    params = request.query_params
    include_closed = params.get("include_closed", "false").lower() == "true"
    limit = int(params.get("limit", "50"))

    query = flask_db.session.query(Ticket).join(
        TicketInventoryItem, TicketInventoryItem.ticket_id == Ticket.id
    ).filter(TicketInventoryItem.inventory_item_id == item_id)

    if not include_closed:
        query = query.filter(~Ticket.status.in_(["CLOSED", "CANCELED"]))

    if "admin" not in user_roles and user_id not in secretary_comp_center:
        conditions = [
            Ticket.requester_id == user_id,
            Ticket.assigned_to_user_id == user_id,
        ]
        if "department_head" in user_roles:
            from itcj.core.services.departments_service import get_user_department
            user_dept = get_user_department(user_id)
            if user_dept:
                conditions.append(Ticket.requester_department_id == user_dept.id)
        query = query.filter(or_(*conditions))

    query = query.order_by(Ticket.created_at.desc())
    if limit > 0:
        query = query.limit(limit)

    tickets = query.all()
    tickets_data = [t.to_dict(include_relations=True) for t in tickets]

    return {
        "item_id": item_id,
        "item": {
            "id": item.id,
            "inventory_number": item.inventory_number,
            "display_name": item.display_name,
            "category": item.category.to_dict() if item.category else None,
            "department": {"id": item.department.id, "name": item.department.name} if item.department else None,
            "assigned_to": {"id": item.assigned_to_user.id, "full_name": item.assigned_to_user.full_name} if item.assigned_to_user else None,
        },
        "tickets": tickets_data,
        "count": len(tickets_data),
        "filters": {"include_closed": include_closed, "limit": limit},
    }
