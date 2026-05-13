"""Páginas de ayuda (manual de usuario) para Mantenimiento.

Cada vista verifica el permiso granular `maint.help.page.{requester|admin|tech}`.
Los tabs visibles en el header se calculan según los perms del usuario.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from itcj2.dependencies import require_page_app
from itcj2.apps.maint.pages.nav import render_maint

router = APIRouter(tags=["maint-help"])


@router.get("/help", name="maint_pages.help_requester")
async def help_requester(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.help.page.requester"])),
) -> HTMLResponse:
    """Manual para solicitantes (todos los roles maint con el perm)."""
    return render_maint(request, "maint/help/requester.html", {
        "page_title": "Ayuda — Solicitantes",
        "active_view": "requester",
    })


@router.get("/help/admin", name="maint_pages.help_admin")
async def help_admin(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.help.page.admin"])),
) -> HTMLResponse:
    """Manual para admin y dispatchers."""
    return render_maint(request, "maint/help/admin.html", {
        "page_title": "Ayuda — Admin / Dispatcher",
        "active_view": "admin",
    })


@router.get("/help/tech", name="maint_pages.help_tech")
async def help_tech(
    request: Request,
    user: dict = Depends(require_page_app("maint", perms=["maint.help.page.tech"])),
) -> HTMLResponse:
    """Manual para técnicos."""
    return render_maint(request, "maint/help/tech.html", {
        "page_title": "Ayuda — Técnicos",
        "active_view": "tech",
    })
