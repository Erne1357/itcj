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
    return render_maint(request, "maint/tickets/create.html", {"active_page": "tickets_create"})


@router.get("/tickets/{ticket_id}", name="maint_pages.tickets.detail")
async def ticket_detail(
    ticket_id: int,
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.tickets.page.detail"])),
) -> HTMLResponse:
    return render_maint(request, "maint/tickets/detail.html", {
        "ticket_id": ticket_id,
        "active_page": "tickets",
    })
