"""
Páginas del área de técnicos de Help-Desk.
Equivalente a itcj/apps/helpdesk/routes/pages/technician.py.

Rutas:
  GET /help-desk/technician/dashboard        → Dashboard personal del técnico
  GET /help-desk/technician/my-assignments   → Tickets asignados al técnico
  GET /help-desk/technician/team             → Vista de tickets del equipo
  GET /help-desk/technician/tickets/{id}     → Detalle de ticket (vista técnico)
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.apps.helpdesk.pages.nav import render_helpdesk
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.helpdesk.pages.technician")

router = APIRouter(prefix="/technician", tags=["helpdesk-pages-technician"])


def _helpdesk_roles(user_id: int) -> set:
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.database import SessionLocal

    _db = SessionLocal()
    try:
        return user_roles_in_app(_db, user_id, "helpdesk")
    finally:
        _db.close()


@router.get("/dashboard", name="helpdesk.pages.technician.dashboard")
async def dashboard(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.dashboard.technician"])),
):
    """Dashboard personal del técnico."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/technician/dashboard.html", {
        "user_roles": user_roles,
        "active_page": "tech_dashboard",
    })


@router.get("/my-assignments", name="helpdesk.pages.technician.my_assignments")
async def my_assignments(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.tickets.page.my_tickets"])),
):
    """Tickets asignados al técnico actual."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/technician/my_assignments.html", {
        "user_roles": user_roles,
        "active_page": "tech_assignments",
    })


@router.get("/team", name="helpdesk.pages.technician.team")
async def team(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.tickets.page.team"])),
):
    """Vista de tickets del equipo técnico."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/technician/team.html", {
        "user_roles": user_roles,
        "active_page": "tech_team",
    })


@router.get("/tickets/{ticket_id}", name="helpdesk.pages.technician.ticket_detail")
async def ticket_detail(
    request: Request,
    ticket_id: int,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.tickets.page.my_tickets"])),
):
    """Vista detallada de un ticket para técnico."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/user/ticket_detail.html", {
        "ticket_id": ticket_id,
        "user_roles": user_roles,
        "active_page": "tech_assignments",
    })
