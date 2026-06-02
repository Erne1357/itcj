"""Páginas de tickets de Mantenimiento."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from itcj2.dependencies import require_page_app
from itcj2.apps.maint.pages.nav import render_maint

router = APIRouter(tags=["maint-pages"])


@router.get("/tickets", name="maint_pages.tickets.list")
async def ticket_list(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.tickets.page.list"])),
) -> HTMLResponse:
    return render_maint(request, "maint/tickets/list.html", {"active_page": "tickets"})


@router.get("/tickets/create", name="maint_pages.tickets.create")
async def ticket_create(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.tickets.page.create"])),
) -> HTMLResponse:
    from itcj2.apps.maint.utils import catalog_cache
    from itcj2.database import get_db as _get_db
    from itcj2.core.services.authz_service import get_user_permissions_for_app

    # Prioridades activas (con is_default) para renderizar las tarjetas desde BD
    priorities = [p for p in catalog_cache.get_priorities() if p.get("is_active")]

    # Flag para mostrar el selector "Solicitar para" en el formulario
    can_create_behalf = False
    if user.get("role") == "admin":
        can_create_behalf = True
    else:
        try:
            db = next(_get_db())
            uid = int(user["sub"])
            user_perms = get_user_permissions_for_app(db, uid, "maint", include_positions=True)
            can_create_behalf = "maint.tickets.api.create.behalf" in user_perms
        except Exception:
            can_create_behalf = False

    return render_maint(request, "maint/tickets/create.html", {
        "active_page": "tickets_create",
        "priorities": priorities,
        "can_create_behalf": can_create_behalf,
    })


@router.get("/tickets/{ticket_id}", name="maint_pages.tickets.detail")
async def ticket_detail(
    ticket_id: int,
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.tickets.page.detail"])),
) -> HTMLResponse:
    from itcj2.database import get_db as _get_db
    from itcj2.core.services.authz_service import get_user_permissions_for_app

    # Coordinadores y admin pueden asignar/desasignar técnicos desde el detalle.
    # Dispatcher y secretaría ya NO asignan (D2 del plan).
    can_assign = False
    if user.get("role") == "admin":
        can_assign = True
    else:
        try:
            db = next(_get_db())
            uid = int(user["sub"])
            user_perms = get_user_permissions_for_app(db, uid, "maint", include_positions=True)
            can_assign = "maint.assignments.api.assign" in user_perms
        except Exception:
            can_assign = False

    return render_maint(request, "maint/tickets/detail.html", {
        "ticket_id": ticket_id,
        "active_page": "tickets",
        "can_assign": can_assign,
    })
