"""
Páginas del panel de administración de Help-Desk.
Equivalente a itcj/apps/helpdesk/routes/pages/admin.py.

Rutas:
  GET /help-desk/admin/home                   → Dashboard de administrador
  GET /help-desk/admin/assign-tickets         → Asignación de tickets
  GET /help-desk/admin/tickets                → Todos los tickets (admin)
  GET /help-desk/admin/tickets-list           → Lista completa de tickets
  GET /help-desk/admin/categories             → Gestión de categorías
  GET /help-desk/admin/inventory              → Redirige a lista de inventario
  GET /help-desk/admin/inventory/create       → Redirige a formulario de creación
  GET /help-desk/admin/inventory/categories   → Categorías de inventario
  GET /help-desk/admin/inventory/reports      → Reportes de inventario
  GET /help-desk/admin/stats                  → Estadísticas del sistema
  GET /help-desk/admin/documents              → Generación de documentos
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from itcj2.apps.helpdesk.pages.nav import render_helpdesk
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.helpdesk.pages.admin")

router = APIRouter(prefix="/admin", tags=["helpdesk-pages-admin"])


@router.get("/home", name="helpdesk.pages.admin.home")
async def home(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.dashboard.admin"])),
):
    """Dashboard principal de administrador de Help-Desk."""
    from itcj2.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(user_id, "helpdesk")

    return render_helpdesk(request, "helpdesk/admin/home.html", {
        "user_roles": user_roles,
        "active_page": "admin_home",
    })


@router.get("/assign-tickets", name="helpdesk.pages.admin.assign_tickets")
async def assign_tickets(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.assignments.page.list"])),
):
    """Vista para asignar y gestionar tickets."""
    from itcj2.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(user_id, "helpdesk")

    return render_helpdesk(request, "helpdesk/admin/assign_tickets.html", {
        "user_roles": user_roles,
        "active_page": "admin_assign_tickets",
    })


@router.get("/tickets", name="helpdesk.pages.admin.all_tickets")
async def all_tickets(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.tickets.page.list"])),
):
    """Vista de todos los tickets del sistema."""
    from itcj2.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(user_id, "helpdesk")

    return render_helpdesk(request, "helpdesk/admin/all_tickets.html", {
        "user_roles": user_roles,
        "active_page": "admin_tickets",
    })


@router.get("/tickets-list", name="helpdesk.pages.admin.tickets_list")
async def tickets_list(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.tickets.page.list_all"])),
):
    """Lista completa de todos los tickets ordenada por fecha de creación descendente."""
    from itcj2.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(user_id, "helpdesk")

    return render_helpdesk(request, "helpdesk/admin/tickets_list.html", {
        "user_roles": user_roles,
        "active_page": "admin_tickets_list",
    })


@router.get("/categories", name="helpdesk.pages.admin.categories")
async def categories(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.categories.page.list"])),
):
    """Gestión de categorías de tickets."""
    from itcj2.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(user_id, "helpdesk")

    return render_helpdesk(request, "helpdesk/admin/categories.html", {
        "user_roles": user_roles,
        "active_page": "admin_categories",
    })


@router.get("/inventory", name="helpdesk.pages.admin.inventory_list")
async def inventory_list(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.page.list"])),
):
    """Redirige a la lista completa de inventario."""
    return RedirectResponse("/help-desk/inventory/items", status_code=302)


@router.get("/inventory/create", name="helpdesk.pages.admin.inventory_create")
async def inventory_create(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.api.create"])),
):
    """Redirige al formulario de creación de equipo."""
    return RedirectResponse("/help-desk/inventory/items/create", status_code=302)


@router.get("/inventory/categories", name="helpdesk.pages.admin.inventory_categories")
async def inventory_categories(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory_categories.page.list"])),
):
    """Gestión de categorías de inventario."""
    from itcj2.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(user_id, "helpdesk")

    return render_helpdesk(request, "helpdesk/admin/inventory_categories.html", {
        "user_roles": user_roles,
        "active_page": "admin_inventory_categories",
    })


@router.get("/inventory/reports", name="helpdesk.pages.admin.inventory_reports")
async def inventory_reports(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.api.export.all"])),
):
    """Reportes de inventario."""
    from itcj2.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(user_id, "helpdesk")

    return render_helpdesk(request, "helpdesk/admin/inventory_reports.html", {
        "user_roles": user_roles,
        "active_page": "admin_inventory_reports",
    })


@router.get("/stats", name="helpdesk.pages.admin.stats")
async def stats(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.stats.page.list"])),
):
    """Estadísticas generales del sistema de tickets."""
    from itcj2.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(user_id, "helpdesk")

    return render_helpdesk(request, "helpdesk/admin/stats.html", {
        "user_roles": user_roles,
        "active_page": "admin_stats",
    })


@router.get("/documents", name="helpdesk.pages.admin.documents")
async def documents(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.documents.page.list"])),
):
    """Generación de documentos PDF/DOCX a partir de tickets."""
    from itcj2.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(user_id, "helpdesk")

    return render_helpdesk(request, "helpdesk/admin/documents.html", {
        "user_roles": user_roles,
        "active_page": "admin_documents",
    })
