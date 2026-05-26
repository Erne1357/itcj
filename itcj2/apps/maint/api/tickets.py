"""Tickets API — maint."""
import logging

from fastapi import APIRouter, HTTPException

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.maint.schemas.tickets import (
    CreateTicketRequest,
    UpdateTicketRequest,
    ResolveTicketRequest,
    RateTicketRequest,
    CancelTicketRequest,
)
from itcj2.apps.maint.services import ticket_service
from itcj2.apps.maint.services.notification_helper import MaintNotificationHelper

router = APIRouter(tags=["maint-tickets"])
logger = logging.getLogger(__name__)


# ==================== DEPARTAMENTOS DEL SOLICITANTE ====================
@router.get("/my-departments")
async def my_departments(
    user: dict = require_perms("maint", ["maint.tickets.api.create"]),
    db: DbSession = None,
):
    """Lista los departamentos activos del usuario logueado (vía UserPosition).

    Usado por el formulario de creación de ticket para:
      - Si len==1: usar automáticamente sin mostrar selector.
      - Si len>1: mostrar selector obligatorio.
      - Si len==0: dejar nulo (warning UI opcional).
    """
    from itcj2.core.models.department import Department
    from itcj2.core.models.position import UserPosition, Position
    uid = int(user["sub"])
    rows = (
        db.query(Department.id, Department.code, Department.name)
        .join(Position, Position.department_id == Department.id)
        .join(UserPosition, UserPosition.position_id == Position.id)
        .filter(
            UserPosition.user_id == uid,
            UserPosition.is_active == True,
        )
        .distinct()
        .order_by(Department.name.asc())
        .all()
    )
    return {
        "success": True,
        "data": [{"id": r[0], "code": r[1], "name": r[2]} for r in rows],
    }


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
    assigned_to: str = None,
    user: dict = require_perms("maint", [
        "maint.tickets.api.read.own",
        "maint.tickets.api.read.department",
        "maint.tickets.api.read.all",
    ]),
    db: DbSession = None,
):
    """`assigned_to=me` filtra a tickets donde el user es técnico activo."""
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
        assigned_to_me=(assigned_to == "me"),
    )
    return {
        **{k: v for k, v in result.items() if k != "tickets"},
        "tickets": [ticket_service.serialize_ticket_summary(t) for t in result["tickets"]],
    }


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
        department_id=body.department_id,
    )
    try:
        MaintNotificationHelper.notify_ticket_created(db, ticket)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("notify_ticket_created failed for ticket %s: %s", ticket.id, exc)
    return {"ticket_id": ticket.id, "ticket_number": ticket.ticket_number, "due_at": ticket.due_at.isoformat() if ticket.due_at else None}


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
    return ticket_service.serialize_ticket_detail(ticket)


# ==================== EDITAR TICKET ====================
@router.patch("/{ticket_id}")
async def update_ticket(
    ticket_id: int,
    body: UpdateTicketRequest,
    user: dict = require_perms("maint", ["maint.tickets.api.edit"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    user_id = int(user["sub"])
    ticket = ticket_service.get_ticket_by_id(db, ticket_id, user_id=user_id)

    user_roles = set(user_roles_in_app(db, user_id, "maint"))
    if ticket.requester_id != user_id and not (user_roles & {"admin", "dispatcher"}):
        raise HTTPException(status_code=403, detail="Solo el solicitante puede editar su ticket")

    updated = ticket_service.update_pending_ticket(
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
    return ticket_service.serialize_ticket_summary(updated)


# ==================== INICIAR PROGRESO ====================
@router.post("/{ticket_id}/start")
async def start_ticket(
    ticket_id: int,
    user: dict = require_perms("maint", ["maint.tickets.api.resolve"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    user_id = int(user["sub"])
    user_roles = list(user_roles_in_app(db, user_id, "maint"))
    ticket = ticket_service.start_progress(db, ticket_id, user_id, user_roles)
    try:
        MaintNotificationHelper.notify_ticket_in_progress(db, ticket)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("notify_ticket_in_progress failed for ticket %s: %s", ticket.id, exc)
    return {"status": ticket.status, "ticket_number": ticket.ticket_number}


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

    is_active_tech = any(
        t.user_id == user_id and t.unassigned_at is None
        for t in ticket.technicians
    )
    can_resolve = is_active_tech or bool(user_roles & {'dispatcher', 'admin'})
    if not can_resolve:
        raise HTTPException(
            status_code=403,
            detail="Solo los técnicos asignados o dispatchers pueden resolver tickets",
        )

    resolved, warnings = ticket_service.resolve_ticket(
        db=db,
        ticket_id=ticket_id,
        resolved_by_id=user_id,
        success=body.success,
        maintenance_type=body.maintenance_type,
        service_origin=body.service_origin,
        resolution_notes=body.resolution_notes,
        time_invested_minutes=body.time_invested_minutes,
        observations=body.observations,
        materials_used=body.materials_used,
    )
    try:
        MaintNotificationHelper.notify_ticket_resolved(db, resolved)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("notify_ticket_resolved failed for ticket %s: %s", resolved.id, exc)
    response = {"status": resolved.status, "ticket_number": resolved.ticket_number}
    if warnings:
        response["warnings"] = warnings
    return response


# ==================== MATERIALES DE ALMACÉN ====================
@router.get("/{ticket_id}/materials")
async def get_ticket_materials(
    ticket_id: int,
    user: dict = require_perms("maint", [
        "maint.tickets.api.read.own",
        "maint.tickets.api.read.department",
        "maint.tickets.api.read.all",
    ]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.models.ticket_material import WarehouseTicketMaterial
    user_id = int(user["sub"])
    ticket_service.get_ticket_by_id(db, ticket_id, user_id=user_id)
    materials = (
        db.query(WarehouseTicketMaterial)
        .filter_by(source_app="maint", source_ticket_id=ticket_id)
        .all()
    )
    return {
        "materials": [
            {
                "product_id": m.product_id,
                "product_name": m.product.name if m.product else None,
                "product_unit": m.product.unit_of_measure if m.product else None,
                "quantity_used": str(m.quantity_used),
                "notes": m.notes,
                "added_at": m.added_at.isoformat() if m.added_at else None,
                "added_by": m.added_by.full_name if m.added_by else None,
            }
            for m in materials
        ]
    }


@router.get("/warehouse-products")
async def search_warehouse_products(
    search: str = None,
    limit: int = 20,
    user: dict = require_perms("maint", ["maint.tickets.api.resolve"]),
    db: DbSession = None,
):
    """Autocomplete de productos del almacén para la resolución de tickets."""
    from itcj2.apps.warehouse.services.product_service import get_available_for_autocomplete
    products = get_available_for_autocomplete(db, "equipment_maint", search, min(limit, 50))
    return {"products": products}


# ==================== CALIFICAR TICKET ====================
@router.post("/{ticket_id}/rate")
async def rate_ticket(
    ticket_id: int,
    body: RateTicketRequest,
    user: dict = require_perms("maint", ["maint.tickets.api.rate"]),
    db: DbSession = None,
):
    user_id = int(user["sub"])
    ticket = ticket_service.rate_ticket(
        db=db,
        ticket_id=ticket_id,
        requester_id=user_id,
        rating_attention=body.rating_attention,
        rating_speed=body.rating_speed,
        rating_efficiency=body.rating_efficiency,
        comment=body.comment,
    )
    try:
        MaintNotificationHelper.notify_ticket_rated(db, ticket)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("notify_ticket_rated failed for ticket %s: %s", ticket.id, exc)
    return {"status": ticket.status, "ticket_number": ticket.ticket_number}


# ==================== CANCELAR TICKET ====================
@router.post("/{ticket_id}/cancel")
async def cancel_ticket(
    ticket_id: int,
    body: CancelTicketRequest,
    user: dict = require_perms("maint", ["maint.tickets.api.cancel"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    user_id = int(user["sub"])
    user_roles = list(user_roles_in_app(db, user_id, "maint"))
    ticket = ticket_service.cancel_ticket(
        db=db,
        ticket_id=ticket_id,
        user_id=user_id,
        reason=body.reason,
        user_roles=user_roles,
    )
    try:
        MaintNotificationHelper.notify_ticket_canceled(db, ticket)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("notify_ticket_canceled failed for ticket %s: %s", ticket.id, exc)
    return {"status": ticket.status, "ticket_number": ticket.ticket_number}
