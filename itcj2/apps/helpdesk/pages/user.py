"""
Páginas del área de usuario final de Help-Desk.
Equivalente a itcj/apps/helpdesk/routes/pages/user.py.

Rutas:
  GET /help-desk/user/create           → Crear ticket
  GET /help-desk/user/my-tickets       → Mis tickets
  GET /help-desk/user/tickets/{id}     → Detalle de ticket
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.apps.helpdesk.pages.nav import render_helpdesk
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.helpdesk.pages.user")

router = APIRouter(prefix="/user", tags=["helpdesk-pages-user"])

MAX_UNRATED_TICKETS = 3

# Dependencia: usuario autenticado con acceso a helpdesk
_require_helpdesk = require_page_app("helpdesk")


@router.get("/create", name="helpdesk.pages.user.create_ticket")
async def create_ticket(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.tickets.page.create"])),
):
    """Página para crear un nuevo ticket."""
    from itcj2.apps.helpdesk.models.ticket import Ticket
    from itcj2.core.models.position import UserPosition
    from itcj2.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(user_id, "helpdesk")

    unrated_count = Ticket.query.filter(
        Ticket.requester_id == user_id,
        Ticket.status.in_(["RESOLVED_SUCCESS", "RESOLVED_FAILED"]),
        Ticket.rating_attention.is_(None),
    ).count()

    can_create_for_other = "admin" in user_roles
    if not can_create_for_other:
        user_positions = UserPosition.query.filter_by(user_id=user_id, is_active=True).all()
        for up in user_positions:
            if up.position and up.position.department:
                if up.position.department.code == "comp_center":
                    can_create_for_other = True
                    break

    return render_helpdesk(request, "helpdesk/user/create_ticket.html", {
        "title": "Crear Ticket",
        "user_roles": user_roles,
        "can_create_for_other": can_create_for_other,
        "unrated_count": unrated_count,
        "max_unrated": MAX_UNRATED_TICKETS,
        "active_page": "create_ticket",
    })


@router.get("/my-tickets", name="helpdesk.pages.user.my_tickets")
async def my_tickets(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.tickets.page.my_tickets"])),
):
    """Lista de tickets del usuario autenticado."""
    from itcj2.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(user_id, "helpdesk")

    return render_helpdesk(request, "helpdesk/user/my_tickets.html", {
        "title": "Mis Tickets",
        "user_roles": user_roles,
        "active_page": "my_tickets",
    })


@router.get("/tickets/{ticket_id}", name="helpdesk.pages.user.ticket_detail")
async def ticket_detail(
    request: Request,
    ticket_id: int,
    user: dict = Depends(require_page_app(
        "helpdesk",
        perms=["helpdesk.tickets.api.read.own", "helpdesk.tickets.api.read.all"],
    )),
):
    """Vista de detalle de un ticket específico."""
    from itcj2.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(user_id, "helpdesk")

    return render_helpdesk(request, "helpdesk/user/ticket_detail.html", {
        "title": f"Ticket #{ticket_id}",
        "ticket_id": ticket_id,
        "user_id": user_id,
        "user_roles": user_roles,
        "active_page": "my_tickets",
    })
