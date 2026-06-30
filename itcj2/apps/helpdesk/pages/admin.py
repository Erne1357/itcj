"""
Páginas del panel de administración de Help-Desk.
Equivalente a itcj/apps/helpdesk/routes/pages/admin.py.

Rutas:
  GET /help-desk/admin/home                   → Dashboard de administrador
  GET /help-desk/admin/assign-tickets         → Asignación de tickets
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


def _helpdesk_roles(user_id: int) -> set:
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.database import SessionLocal

    _db = SessionLocal()
    try:
        return user_roles_in_app(_db, user_id, "helpdesk")
    finally:
        _db.close()


def _query_tickets_ctx(request: Request, user_id: int, user_roles: set) -> dict:
    """Consulta la lista de tickets para la vista admin.

    Reusado por la PÁGINA (`tickets_list`, render completo) y el PARTIAL HTMX
    (`tickets_list_partial`, fragmento). Reusa `ticket_service.list_tickets`
    (mismo motor que el endpoint API). Devuelve también la selección actual de
    filtros para prefijar el form en el render completo.
    """
    from itcj2.apps.helpdesk.services import ticket_service
    from itcj2.database import SessionLocal

    p = request.query_params
    status = p.get("status")
    if status:
        status = [s.strip().upper() for s in status.split(",") if s.strip()] or None
    try:
        page = max(1, int(p.get("page", "1")))
    except (ValueError, TypeError):
        page = 1

    _db = SessionLocal()
    try:
        result = ticket_service.list_tickets(
            _db,
            user_id=user_id,
            user_roles=user_roles,
            status=status,
            area=p.get("area") or None,
            priority=p.get("priority") or None,
            search=(p.get("search", "") or "").strip() or None,
            page=page,
            per_page=20,
        )
    finally:
        _db.close()

    return {
        "tickets": result["tickets"],
        "total": result["total"],
        "current_page": result["current_page"],
        "total_pages": result["pages"],
        # selección actual de filtros (prefija el form en el render completo)
        "f_status": p.get("status", ""),
        "f_area": p.get("area", ""),
        "f_priority": p.get("priority", ""),
        "f_search": p.get("search", ""),
    }


def _query_documents_ctx(request: Request, user_id: int, user_roles: set) -> dict:
    """Consulta tickets de SOPORTE para la generación de documentos.

    Reusado por la PÁGINA (render completo) y el PARTIAL HTMX (fragmento). El
    filtro de fecha se aplica en Python sobre el resultado (la vista no pagina:
    trae hasta 500 tickets de Soporte, como hacía el render JS anterior).
    """
    from itcj2.apps.helpdesk.services import ticket_service
    from itcj2.database import SessionLocal

    p = request.query_params
    status = p.get("status") or None
    search = (p.get("search", "") or "").strip() or None
    date_from = (p.get("date_from", "") or "").strip() or None
    date_to = (p.get("date_to", "") or "").strip() or None

    _db = SessionLocal()
    try:
        result = ticket_service.list_tickets(
            _db,
            user_id=user_id,
            user_roles=user_roles,
            area="SOPORTE",  # solo Soporte genera documentos oficiales
            status=[status] if status else None,
            search=search,
            page=1,
            per_page=500,
        )
    finally:
        _db.close()

    tickets = result["tickets"]
    if date_from:
        tickets = [t for t in tickets if t.get("created_at") and t["created_at"][:10] >= date_from]
    if date_to:
        tickets = [t for t in tickets if t.get("created_at") and t["created_at"][:10] <= date_to]

    return {
        "tickets": tickets,
        "total": len(tickets),
        "f_status": p.get("status", ""),
        "f_search": p.get("search", ""),
        "f_date_from": date_from or "",
        "f_date_to": date_to or "",
        "has_filters": bool(status or search or date_from or date_to),
    }


@router.get("/home", name="helpdesk.pages.admin.home")
async def home(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.dashboard.admin"])),
):
    """Dashboard principal de administrador de Help-Desk."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

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
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/admin/assign_tickets.html", {
        "user_roles": user_roles,
        "active_page": "admin_assign_tickets",
    })


@router.get("/tickets-list", name="helpdesk.pages.admin.tickets_list")
async def tickets_list(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.tickets.page.list_all"])),
):
    """Lista de tickets.

    Una sola URL sirve dos representaciones (patrón canónico HTMX):
      - petición normal o boosteada → PÁGINA completa.
      - petición HTMX no-boost (filtros/paginación) → solo el FRAGMENTO de
        resultados (#hd-tickets-results) + contador OOB.
    Así ``hx-push-url`` empuja la URL bonita de la página (compartible, back/fwd).
    """
    from itcj2.templates import render

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)
    ctx = _query_tickets_ctx(request, user_id, user_roles)

    is_htmx = request.headers.get("hx-request") == "true"
    is_boost = request.headers.get("hx-boosted") == "true"
    if is_htmx and not is_boost:
        ctx["oob"] = True
        return render(request, "helpdesk/admin/_tickets_list_results.html", ctx)

    ctx.update({"user_roles": user_roles, "active_page": "admin_tickets_list"})
    return render_helpdesk(request, "helpdesk/admin/tickets_list.html", ctx)


@router.get("/categories", name="helpdesk.pages.admin.categories")
async def categories(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.categories.page.list"])),
):
    """Categorías de tickets — unificadas en el tab de Configuración.

    La página standalone quedó superseded por `config/categories_tab.js`.
    Se mantiene la ruta como redirect para bookmarks/links viejos.
    """
    return RedirectResponse("/help-desk/admin/config#categorias", status_code=302)


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
    """Categorías de inventario — unificadas en el tab de Configuración.

    La página standalone quedó superseded por `config/inventory_categories_tab.js`.
    Se mantiene la ruta como redirect para bookmarks/links viejos.
    """
    return RedirectResponse("/help-desk/admin/config#inv-cat", status_code=302)


@router.get("/inventory/reports", name="helpdesk.pages.admin.inventory_reports")
async def inventory_reports(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.inventory.api.export.all"])),
):
    """Reportes de inventario."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

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
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/admin/stats.html", {
        "user_roles": user_roles,
        "active_page": "admin_stats",
    })


@router.get("/analysis", name="helpdesk.pages.admin.analysis")
async def analysis(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.stats.page.list"])),
):
    """Análisis avanzado de datos: outliers, clustering K-means, distribuciones, tendencias."""
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/admin/analysis.html", {
        "user_roles": user_roles,
        "active_page": "admin_analysis",
    })


@router.get("/config", name="helpdesk.pages.admin.config")
async def config(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.config.page.view"])),
):
    """Pestaña de configuración del módulo Helpdesk.

    Tabs disponibles (cargados de forma perezosa por JS):
      - Categorías y campos personalizados
      - Categorías de inventario
      - Prioridades y SLA
      - Estados y transiciones
      - Áreas
      - Plantillas de notificación
      - Auditoría
    """
    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    return render_helpdesk(request, "helpdesk/admin/config.html", {
        "user_roles": user_roles,
        "active_page": "admin_config",
    })


@router.get("/documents", name="helpdesk.pages.admin.documents")
async def documents(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.documents.page.list"])),
):
    """Generación de documentos PDF/DOCX a partir de tickets.

    Una sola URL sirve dos representaciones (patrón canónico HTMX): petición HTMX
    no-boost (filtros) → solo el FRAGMENTO de la lista; si no → la PÁGINA completa.
    """
    from itcj2.templates import render

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)
    ctx = _query_documents_ctx(request, user_id, user_roles)

    is_htmx = request.headers.get("hx-request") == "true"
    is_boost = request.headers.get("hx-boosted") == "true"
    if is_htmx and not is_boost:
        ctx["oob"] = True
        return render(request, "helpdesk/admin/_documents_results.html", ctx)

    ctx.update({"user_roles": user_roles, "active_page": "admin_documents"})
    return render_helpdesk(request, "helpdesk/admin/documents.html", ctx)
