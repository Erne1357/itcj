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


_TICKETS_SORT_VALUES = {"oldest", "priority", "stale"}

_TICKETS_STATUS_LABELS = {
    "PENDING": "Pendiente", "ASSIGNED": "Asignado", "IN_PROGRESS": "En Progreso",
    "RESOLVED_SUCCESS": "Resuelto", "RESOLVED_FAILED": "No Resuelto",
    "CLOSED": "Cerrado", "CANCELED": "Cancelado",
}
_TICKETS_AREA_LABELS = {"DESARROLLO": "Desarrollo", "SOPORTE": "Soporte"}
_TICKETS_PRIORITY_LABELS = {"URGENTE": "Urgente", "ALTA": "Alta", "MEDIA": "Media", "BAJA": "Baja"}
_TICKETS_SORT_LABELS = {"oldest": "Más antiguos", "priority": "Por prioridad", "stale": "Sin actualizar"}


def _parse_tickets_filters(qp) -> dict:
    """Parsea los query params de la lista de tickets (admin) a kwargs para
    `ticket_service.list_tickets` + valores de display (`f_*`) para prefijar el
    form. Función PURA (sin BD) — testable en aislamiento con un dict plano.

    `qp` es cualquier objeto con `.get(name, default='')` (`request.query_params`
    o un dict normal en tests).
    """
    status = qp.get("status")
    if status:
        status = [s.strip().upper() for s in status.split(",") if s.strip()] or None
    try:
        page = max(1, int(qp.get("page", "1")))
    except (ValueError, TypeError):
        page = 1

    area = qp.get("area") or None
    priority = qp.get("priority") or None
    search = (qp.get("search", "") or "").strip() or None

    # --- Técnico asignado: id numérico | 'unassigned' | 'team:<area>' ---
    raw_technician = (qp.get("technician", "") or "").strip()
    assigned_to_user_id = None
    unassigned = False
    assigned_to_team = None
    if raw_technician.isdigit():
        assigned_to_user_id = int(raw_technician)
    elif raw_technician == "unassigned":
        unassigned = True
    elif raw_technician.startswith("team:"):
        assigned_to_team = raw_technician.split(":", 1)[1].strip().lower() or None
        if not assigned_to_team:
            raw_technician = ""
    else:
        raw_technician = ""  # valor no reconocido: se ignora, no queda "activo"

    # --- Categoría ---
    raw_category = (qp.get("category", "") or "").strip()
    category_id = int(raw_category) if raw_category.isdigit() else None
    if raw_category and category_id is None:
        raw_category = ""

    # --- Depto. solicitante: SIEMPRE se intersecta con el scope visible dentro
    # de `list_tickets` (nunca lo sustituye) — mismo mecanismo que ya usa el
    # scope departamental de la lista, no uno paralelo. ---
    raw_dept = (qp.get("req_department", "") or "").strip()
    department_ids = {int(raw_dept)} if raw_dept.isdigit() else None
    if raw_dept and department_ids is None:
        raw_dept = ""

    # --- Rango de fechas (creación) ---
    from datetime import date as _date
    raw_start = (qp.get("start", "") or "").strip()
    raw_end = (qp.get("end", "") or "").strip()
    created_from = None
    created_to = None
    if raw_start:
        try:
            created_from = _date.fromisoformat(raw_start)
        except ValueError:
            raw_start = ""
    if raw_end:
        try:
            created_to = _date.fromisoformat(raw_end)
        except ValueError:
            raw_end = ""

    # --- Orden: sustituye el order_by por defecto, no lo envuelve ---
    raw_sort = (qp.get("sort") or "").strip().lower()
    sort = raw_sort if raw_sort in _TICKETS_SORT_VALUES else "recent"
    f_sort = raw_sort if raw_sort in _TICKETS_SORT_VALUES else ""

    more_active = bool(raw_technician or raw_category or raw_dept or raw_start or raw_end or f_sort)

    return {
        "kwargs": dict(
            status=status,
            area=area,
            priority=priority,
            search=search,
            assigned_to_user_id=assigned_to_user_id,
            unassigned=unassigned,
            assigned_to_team=assigned_to_team,
            category_id=category_id,
            department_ids=department_ids,
            created_from=created_from,
            created_to=created_to,
            sort=sort,
            page=page,
            per_page=20,
        ),
        "display": {
            "f_status": qp.get("status", ""),
            "f_area": qp.get("area", ""),
            "f_priority": qp.get("priority", ""),
            "f_search": qp.get("search", ""),
            "f_technician": raw_technician,
            "f_category": raw_category,
            "f_req_department": raw_dept,
            "f_start": raw_start,
            "f_end": raw_end,
            "f_sort": f_sort,
        },
        "raw": {
            "status": qp.get("status", "") or "",
            "area": area,
            "priority": priority,
            "search": search,
            "technician": raw_technician,
            "category": raw_category,
            "req_department": raw_dept,
            "start": raw_start,
            "end": raw_end,
            "sort": f_sort,
        },
        "more_active": more_active,
    }


def _build_filter_chips(db, raw: dict) -> list:
    """Un chip por filtro activo de la lista de tickets (quitable individualmente
    desde el JS vía `data-chip-remove="<param>"`). Hace lookups PUNTUALES (no las
    listas completas) para resolver nombres legibles de técnico/categoría/depto —
    barato incluso en el fragmento HTMX de cada cambio de filtro.
    """
    from itcj2.apps.helpdesk.models.category import Category
    from itcj2.core.models.department import Department
    from itcj2.core.models.user import User

    chips = []

    if raw.get("status"):
        for code in [s.strip().upper() for s in raw["status"].split(",") if s.strip()]:
            chips.append({"param": "status", "label": f"Estado: {_TICKETS_STATUS_LABELS.get(code, code)}"})
    if raw.get("area"):
        chips.append({"param": "area", "label": f"Área: {_TICKETS_AREA_LABELS.get(raw['area'], raw['area'])}"})
    if raw.get("priority"):
        chips.append({"param": "priority", "label": f"Prioridad: {_TICKETS_PRIORITY_LABELS.get(raw['priority'], raw['priority'])}"})
    if raw.get("search"):
        chips.append({"param": "search", "label": f"Buscar: {raw['search']}"})

    tech = raw.get("technician") or ""
    if tech.isdigit():
        u = db.get(User, int(tech))
        chips.append({"param": "technician", "label": f"Técnico: {u.full_name if u else tech}"})
    elif tech == "unassigned":
        chips.append({"param": "technician", "label": "Técnico: Sin asignar"})
    elif tech.startswith("team:"):
        team = tech.split(":", 1)[1].strip().capitalize()
        chips.append({"param": "technician", "label": f"Técnico: Cola de {team}"})

    cat = raw.get("category") or ""
    if cat.isdigit():
        c = db.get(Category, int(cat))
        chips.append({"param": "category", "label": f"Categoría: {c.name if c else cat}"})

    dept = raw.get("req_department") or ""
    if dept.isdigit():
        d = db.get(Department, int(dept))
        chips.append({"param": "req_department", "label": f"Depto. solicitante: {d.name if d else dept}"})

    if raw.get("start"):
        chips.append({"param": "start", "label": f"Desde: {raw['start']}"})
    if raw.get("end"):
        chips.append({"param": "end", "label": f"Hasta: {raw['end']}"})

    if raw.get("sort"):
        chips.append({"param": "sort", "label": f"Orden: {_TICKETS_SORT_LABELS.get(raw['sort'], raw['sort'])}"})

    return chips


def _tickets_filter_options() -> dict:
    """Opciones server-side para los selects del panel "Más filtros" — SOLO se
    necesitan en el render de la PÁGINA completa (el fragmento HTMX de resultados
    no vuelve a pintar la barra de filtros, así que pedirlas en cada cambio de
    filtro sería trabajo de BD desperdiciado)."""
    from itcj2.apps.helpdesk.models.category import Category
    from itcj2.apps.helpdesk.services import assignment_service
    from itcj2.core.models.department import Department
    from itcj2.database import SessionLocal

    _db = SessionLocal()
    try:
        technicians_desarrollo = assignment_service.get_technicians_by_area(_db, "DESARROLLO")
        technicians_soporte = assignment_service.get_technicians_by_area(_db, "SOPORTE")
        categories = (
            _db.query(Category)
            .filter_by(is_active=True)
            .order_by(Category.area, Category.display_order, Category.name)
            .all()
        )
        departments = (
            _db.query(Department)
            .filter_by(is_active=True)
            .order_by(Department.name)
            .all()
        )
    finally:
        _db.close()

    return {
        "technicians_desarrollo": technicians_desarrollo,
        "technicians_soporte": technicians_soporte,
        "categories_desarrollo": [c for c in categories if c.area == "DESARROLLO"],
        "categories_soporte": [c for c in categories if c.area == "SOPORTE"],
        "departments": departments,
    }


def _query_tickets_ctx(request: Request, user_id: int, user_roles: set) -> dict:
    """Consulta la lista de tickets para la vista admin.

    Reusado por la PÁGINA (`tickets_list`, render completo) y el PARTIAL HTMX
    (`tickets_list_partial`, fragmento). Reusa `ticket_service.list_tickets`
    (mismo motor que el endpoint API). Devuelve también la selección actual de
    filtros (para prefijar el form) y los chips de filtros activos.
    """
    from itcj2.apps.helpdesk.services import ticket_service
    from itcj2.database import SessionLocal

    parsed = _parse_tickets_filters(request.query_params)

    _db = SessionLocal()
    try:
        result = ticket_service.list_tickets(
            _db,
            user_id=user_id,
            user_roles=user_roles,
            **parsed["kwargs"],
        )
        chips = _build_filter_chips(_db, parsed["raw"])
    finally:
        _db.close()

    return {
        "tickets": result["tickets"],
        "total": result["total"],
        "current_page": result["current_page"],
        "total_pages": result["pages"],
        # selección actual de filtros (prefija el form en el render completo)
        **parsed["display"],
        "more_active": parsed["more_active"],
        "chips": chips,
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


def _query_assign_lists_ctx(request: Request, user_id: int, user_roles: set, tab: str = None) -> dict:
    """Consulta las listas de tickets para la vista de asignación.

    Si ``tab`` es None devuelve las tres listas completas (render de página
    entera). Si ``tab`` es 'queue'|'assigned'|'inprogress' devuelve solo esa
    lista (render de fragmento HTMX).
    """
    from itcj2.apps.helpdesk.services import ticket_service
    from itcj2.database import SessionLocal

    _STATUS_MAP = {
        "queue":      ["PENDING"],
        "assigned":   ["ASSIGNED"],
        "inprogress": ["IN_PROGRESS"],
    }
    _PER_PAGE_MAP = {
        "queue":      500,
        "assigned":   200,
        "inprogress": 200,
    }

    _db = SessionLocal()
    try:
        if tab is not None:
            statuses   = _STATUS_MAP.get(tab, ["PENDING"])
            per_page   = _PER_PAGE_MAP.get(tab, 200)
            result     = ticket_service.list_tickets(
                _db, user_id=user_id, user_roles=user_roles,
                status=statuses, per_page=per_page,
            )
            tickets = result["tickets"]
            return {"tickets": tickets, "count": len(tickets), "tab": tab}

        # Full page: three lists
        r_pending = ticket_service.list_tickets(
            _db, user_id=user_id, user_roles=user_roles,
            status=["PENDING"], per_page=500,
        )
        r_assigned = ticket_service.list_tickets(
            _db, user_id=user_id, user_roles=user_roles,
            status=["ASSIGNED"], per_page=200,
        )
        r_inprogress = ticket_service.list_tickets(
            _db, user_id=user_id, user_roles=user_roles,
            status=["IN_PROGRESS"], per_page=200,
        )
    finally:
        _db.close()

    return {
        "t_pending":        r_pending["tickets"],
        "t_pending_count":  len(r_pending["tickets"]),
        "t_assigned":       r_assigned["tickets"],
        "t_assigned_count": len(r_assigned["tickets"]),
        "t_inprogress":       r_inprogress["tickets"],
        "t_inprogress_count": len(r_inprogress["tickets"]),
    }


@router.get("/assign-tickets", name="helpdesk.pages.admin.assign_tickets")
async def assign_tickets(
    request: Request,
    user: dict = Depends(require_page_app("helpdesk", perms=["helpdesk.assignments.page.list"])),
):
    """Vista para asignar y gestionar tickets.

    Una sola URL sirve dos representaciones (patrón canónico HTMX):
      - petición HTMX no-boost con ``?tab=`` → solo el FRAGMENTO de esa lista.
      - petición normal o boosteada → PÁGINA completa con las 3 listas server-side.
    """
    from itcj2.templates import render

    user_id = int(user["sub"])
    user_roles = _helpdesk_roles(user_id)

    is_htmx  = request.headers.get("hx-request") == "true"
    is_boost = request.headers.get("hx-boosted") == "true"
    if is_htmx and not is_boost:
        tab = request.query_params.get("tab", "queue")
        ctx = _query_assign_lists_ctx(request, user_id, user_roles, tab=tab)
        ctx["oob"] = True
        return render(request, "helpdesk/admin/_assign_results.html", ctx)

    ctx = _query_assign_lists_ctx(request, user_id, user_roles)
    ctx.update({"user_roles": user_roles, "active_page": "admin_assign_tickets"})
    return render_helpdesk(request, "helpdesk/admin/assign_tickets.html", ctx)


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
    ctx.update(_tickets_filter_options())
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
    user: dict = Depends(require_page_app("helpdesk", perms=[
        "helpdesk.inventory.api.export.all",
        # El jefe con scope por subárbol también llega a esta página; los reportes
        # que genera ya vienen acotados a sus departamentos visibles.
        "helpdesk.inventory.api.export.subtree",
    ])),
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
    user: dict = Depends(require_page_app("helpdesk", perms=[
        "helpdesk.stats.page.list", "helpdesk.stats.page.list.subtree",
    ])),
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
    user: dict = Depends(require_page_app("helpdesk", perms=[
        "helpdesk.stats.page.list", "helpdesk.stats.page.list.subtree",
    ])),
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
