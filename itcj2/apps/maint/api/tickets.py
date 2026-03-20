"""Tickets API — maint."""
import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.maint.schemas.tickets import (
    CreateTicketRequest,
    UpdateTicketRequest,
    ResolveTicketRequest,
    RateTicketRequest,
    CancelTicketRequest,
)
from itcj2.apps.maint.services import ticket_service

router = APIRouter(tags=["maint-tickets"])
logger = logging.getLogger(__name__)


# ==================== LISTAR TICKETS ====================
@router.get("")
@router.get("/")
async def list_tickets(
    status: str = None,
    category_id: int = None,
    priority: str = None,
    search: str = None,
    page: int = 1,
    per_page: int = 20,
    user: dict = require_perms("maint", [
        "maint.tickets.api.read.own",
        "maint.tickets.api.read.department",
        "maint.tickets.api.read.all",
    ]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "maint")

    result = ticket_service.list_tickets(
        db=db,
        user_id=user_id,
        user_roles=user_roles,
        status=status,
        category_id=category_id,
        priority=priority,
        search=search,
        page=page,
        per_page=per_page,
    )
    return result


# ==================== CREAR TICKET ====================
@router.post("", status_code=201)
@router.post("/")
async def create_ticket(
    body: CreateTicketRequest,
    user: dict = require_perms("maint", ["maint.tickets.api.create"]),
    db: DbSession = None,
):
    user_id = int(user["sub"])
    ticket = ticket_service.create_ticket(
        db=db,
        requester_id=user_id,
        category_id=body.category_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        location=body.location,
        custom_fields=body.custom_fields,
        created_by_id=user_id,
    )
    return {"ticket_id": ticket.id, "ticket_number": ticket.ticket_number, "due_at": ticket.due_at}


# ==================== VER DETALLE ====================
@router.get("/{ticket_id}")
async def get_ticket(
    ticket_id: int,
    user: dict = require_perms("maint", [
        "maint.tickets.api.read.own",
        "maint.tickets.api.read.department",
        "maint.tickets.api.read.all",
    ]),
    db: DbSession = None,
):
    user_id = int(user["sub"])
    ticket = ticket_service.get_ticket_by_id(db, ticket_id, user_id=user_id)
    return ticket


# ==================== EDITAR TICKET ====================
@router.patch("/{ticket_id}")
async def update_ticket(
    ticket_id: int,
    body: UpdateTicketRequest,
    user: dict = require_perms("maint", ["maint.tickets.api.edit"]),
    db: DbSession = None,
):
    user_id = int(user["sub"])
    ticket = ticket_service.get_ticket_by_id(db, ticket_id, user_id=user_id)

    if ticket.requester_id != user_id and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo el solicitante puede editar su ticket")

    return ticket_service.update_pending_ticket(
        db=db,
        ticket_id=ticket_id,
        updated_by_id=user_id,
        category_id=body.category_id,
        priority=body.priority,
        title=body.title,
        description=body.description,
        location=body.location,
        custom_fields=body.custom_fields,
    )


# ==================== RESOLVER TICKET ====================
@router.post("/{ticket_id}/resolve")
async def resolve_ticket(
    ticket_id: int,
    body: ResolveTicketRequest,
    user: dict = require_perms("maint", ["maint.tickets.api.resolve"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    user_id = int(user["sub"])
    user_roles = set(user_roles_in_app(db, user_id, "maint"))

    ticket = ticket_service.get_ticket_by_id(db, ticket_id)

    # Técnico: solo si está activamente asignado al ticket
    # Dispatcher: puede resolver cualquier ticket (sin restricción de asignación)
    is_active_tech = any(
        t.user_id == user_id and t.unassigned_at is None
        for t in ticket.technicians
    )
    can_resolve = (
        is_active_tech
        or bool(user_roles & {'dispatcher', 'admin'})
    )
    if not can_resolve:
        raise HTTPException(
            status_code=403,
            detail="Solo los técnicos asignados o dispatchers pueden resolver tickets",
        )

    return ticket_service.resolve_ticket(
        db=db,
        ticket_id=ticket_id,
        resolved_by_id=user_id,
        success=body.success,
        maintenance_type=body.maintenance_type,
        service_origin=body.service_origin,
        resolution_notes=body.resolution_notes,
        time_invested_minutes=body.time_invested_minutes,
        observations=body.observations,
    )


# ==================== CALIFICAR TICKET ====================
@router.post("/{ticket_id}/rate")
async def rate_ticket(
    ticket_id: int,
    body: RateTicketRequest,
    user: dict = require_perms("maint", ["maint.tickets.api.rate"]),
    db: DbSession = None,
):
    user_id = int(user["sub"])
    return ticket_service.rate_ticket(
        db=db,
        ticket_id=ticket_id,
        requester_id=user_id,
        rating_attention=body.rating_attention,
        rating_speed=body.rating_speed,
        rating_efficiency=body.rating_efficiency,
        comment=body.comment,
    )


# ==================== CANCELAR TICKET ====================
@router.post("/{ticket_id}/cancel")
async def cancel_ticket(
    ticket_id: int,
    body: CancelTicketRequest,
    user: dict = require_perms("maint", ["maint.tickets.api.cancel"]),
    db: DbSession = None,
):
    user_id = int(user["sub"])
    return ticket_service.cancel_ticket(
        db=db,
        ticket_id=ticket_id,
        user_id=user_id,
        reason=body.reason,
    )
