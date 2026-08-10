"""
Helpers de navegación y renderizado para páginas de Help-Desk.

``render_helpdesk()`` es el equivalente FastAPI del context_processor
``inject_helpdesk_nav()`` de Flask: inyecta automáticamente
``helpdesk_nav_items`` y ``current_route`` en cada página de la app.
"""
from __future__ import annotations

import logging
import re

from fastapi import Request
from fastapi.responses import HTMLResponse

from itcj2.templates import ENDPOINT_MAP, render, sv

logger = logging.getLogger("itcj2.apps.helpdesk.pages")

# ---------------------------------------------------------------------------
# Navegación HTMX (hx-boost + idiomorph morph) — fuente única de verdad
# ---------------------------------------------------------------------------
# Rollback global del boost: poner en False → toda la app vuelve a navegación
# clásica al instante (los módulos siguen registrando init en la carga inicial).
HTMX_BOOST_ENABLED = True

# Mapa: hd_page -> lista de módulos JS a cargar para esa página.
#   · hd_page es la clave ÚNICA por template (derivada del path con
#     _template_to_key), NO active_page: varias páginas comparten active_page
#     (ej. items_list/item_create/item_detail = "inventory_items") pero cada
#     template tiene su propio hd_page (inventory_items_items_list, etc.).
#     Para piloto/almacén el derivado coincide con el nombre histórico
#     (admin/home.html -> admin_home; warehouse/dashboard.html -> warehouse_dashboard).
#   · Una entrada aquí = página MIGRADA al controller HelpdeskPage (navegable
#     por boost). Lista vacía = página migrada SIN JS propio (ej. categorías).
#   · Las rutas relativas se sirven desde /static/helpdesk/ y se versionan con
#     sv(); las URLs http(s):// (CDN: Chart, ApexCharts, Sortable, Shepherd) se
#     pasan tal cual. Orden = orden de carga (deps CDN antes que el módulo app).
HD_PAGE_MODULES: dict[str, list[str]] = {
    "admin_config": [
        "https://cdn.jsdelivr.net/npm/sortablejs@1.15.0/Sortable.min.js",
        "js/admin/config/field_template_builder.js",
        "js/admin/config/categories_tab.js",
        "js/admin/config/inventory_categories_tab.js",
        "js/admin/config/priorities_tab.js",
        "js/admin/config/statuses_tab.js",
        "js/admin/config/transitions_matrix.js",
        "js/admin/config/areas_tab.js",
        "js/admin/config/audit_tab.js",
        "js/admin/config/notifications_tab.js",
        "js/admin/config/config_main.js",
    ],
    "admin_stats": ["https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js", "js/shared/ticket-summary.js", "js/admin/stats.js"],
    "admin_analysis": ["https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js", "https://cdn.jsdelivr.net/npm/apexcharts@3.44.0/dist/apexcharts.min.js", "js/shared/ticket-summary.js", "js/admin/analysis.js"],
    "admin_documents": ["js/admin/documents.js"],
    "admin_home": ["js/admin/home.js"],
    "admin_assign_tickets": ["js/admin/assign_tickets.js"],
    "admin_tickets_list": ["js/admin/tickets_list.js"],
    "warehouse_dashboard": ["js/warehouse/dashboard.js"],
    "warehouse_categories": ["js/warehouse/categories.js"],
    "warehouse_products": ["js/warehouse/products.js"],
    "warehouse_entries": ["js/warehouse/entries.js"],
    "warehouse_movements": ["js/warehouse/movements.js"],
    "warehouse_reports": ["js/warehouse/reports.js"],
    "inventory_campaigns_campaigns_list": ["js/inventory/campaigns/campaigns_list.js"],
    "inventory_campaigns_campaign_create": ["js/inventory/campaigns/campaign_create.js"],
    "inventory_campaigns_campaign_detail": ["js/inventory/campaigns/campaign_detail.js"],
    "inventory_campaigns_campaign_validate": ["js/inventory/campaigns/campaign_validate.js"],
    "inventory_retirement_retirement_requests_list": ["js/inventory/retirement/retirement_requests_list.js"],
    "inventory_retirement_retirement_request_create": ["js/inventory/retirement/retirement_request_create.js"],
    "inventory_retirement_retirement_request_detail": ["js/inventory/retirement/retirement_request_detail.js"],
    "inventory_items_items_list": ["js/inventory/items/items_list.js"],
    "inventory_items_item_create": ["js/inventory/items/item_create.js"],
    "inventory_items_item_detail": ["js/inventory/items/item_detail.js"],
    "inventory_items_pending_items": ["js/inventory/items/pending_items.js"],
    "inventory_groups_groups_list": ["js/inventory/groups/groups_list.js"],
    "inventory_groups_group_detail": ["js/inventory/groups/group_detail.js"],
    "inventory_dashboard": [
        "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js",
        "js/inventory/dashboard.js",
    ],
    "inventory_assignment_assign_equipment": ["js/inventory/assignment/assign_equipment.js"],
    "inventory_assignment_my_equipment": [
        "js/inventory/assignment/my_equipment_modal.js",
        "js/inventory/assignment/my_equipment.js",
    ],
    "inventory_reports_verification": ["js/inventory/reports/verification.js"],
    "inventory_reports_reports": ["js/inventory/reports/reports.js"],
    # Reportes de sub-páginas (redirigen a /reports?tab=…; templates ya no se sirven
    # directamente — se registran para que hx-boost no se rompa si alguien llega aquí).
    "inventory_reports_lifecycle": [],
    "inventory_reports_maintenance": [],
    "inventory_reports_warranty": [],
    # Página de reportes de inventario (admin) — índice estático con links a sub-reportes.
    "admin_inventory_reports": [],
    # Reportes del departamento (jefe de depto) — placeholder estático.
    "department_head_reports": [],
    # Landing de Help-Desk — página standalone; se registra para habilitar boost
    # del brand link (base_helpdesk.html) cuando htmx_boost_enabled está activo.
    "home_landing": [],
    "technician_dashboard": ["js/technician/warehouse_ticket.js", "js/technician/dashboard.js"],
    "secretary_dashboard": ["js/secretary/dashboard.js"],
    "department_head_dashboard": ["js/department_head/dashboard.js"],
    "user_my_tickets": [
        "https://cdn.jsdelivr.net/npm/shepherd.js@11.2.0/dist/js/shepherd.min.js",
        "js/user/ticket_tutorial.js",
        "js/user/my_tickets.js",
    ],
    "user_create_ticket": [
        "https://cdn.jsdelivr.net/npm/shepherd.js@11.2.0/dist/js/shepherd.min.js",
        "js/user/ticket_tutorial.js",
        "js/user/create_ticket.js",
    ],
    "user_ticket_detail": [
        "https://cdn.jsdelivr.net/npm/shepherd.js@11.2.0/dist/js/shepherd.min.js",
        "js/user/ticket_tutorial.js",
        "js/user/warehouse_ticket.js",
        "js/user/ticket_detail.js",
    ],
}

# Mapa endpoint de nav (estilo Flask) -> hd_page destino. Permite saber si un
# link del nav apunta a una página migrada (y por tanto debe boostearse). El
# valor es el hd_page (clave única por template) de la página destino.
ENDPOINT_TO_ACTIVE_PAGE: dict[str, str] = {
    "helpdesk_pages.admin_pages.config": "admin_config",
    "helpdesk_pages.admin_pages.stats": "admin_stats",
    "helpdesk_pages.admin_pages.analysis": "admin_analysis",
    "helpdesk_pages.admin_pages.documents": "admin_documents",
    "helpdesk_pages.admin_pages.home": "admin_home",
    "helpdesk_pages.admin_pages.assign_tickets": "admin_assign_tickets",
    "helpdesk_pages.admin_pages.tickets_list": "admin_tickets_list",
    "helpdesk_pages.warehouse_pages.dashboard": "warehouse_dashboard",
    "helpdesk_pages.warehouse_pages.categories": "warehouse_categories",
    "helpdesk_pages.warehouse_pages.products": "warehouse_products",
    "helpdesk_pages.warehouse_pages.entries": "warehouse_entries",
    "helpdesk_pages.warehouse_pages.movements": "warehouse_movements",
    "helpdesk_pages.warehouse_pages.reports": "warehouse_reports",
    "helpdesk_pages.inventory_pages.campaigns_list": "inventory_campaigns_campaigns_list",
    "helpdesk_pages.inventory_pages.retirement_requests_list": "inventory_retirement_retirement_requests_list",
    "helpdesk_pages.inventory_pages.items_list": "inventory_items_items_list",
    "helpdesk_pages.inventory_pages.item_create": "inventory_items_item_create",
    "helpdesk_pages.inventory_pages.bulk_register": "inventory_items_item_create",
    "helpdesk_pages.inventory_pages.pending_items": "inventory_items_pending_items",
    "helpdesk_pages.inventory_pages.groups_list": "inventory_groups_groups_list",
    "helpdesk_pages.inventory_pages.dashboard": "inventory_dashboard",
    "helpdesk_pages.inventory_pages.assign_equipment": "inventory_assignment_assign_equipment",
    "helpdesk_pages.inventory_pages.my_equipment": "inventory_assignment_my_equipment",
    "helpdesk_pages.inventory_pages.verification": "inventory_reports_verification",
    "helpdesk_pages.inventory_pages.reports": "inventory_reports_reports",
    "helpdesk_pages.technician_pages.dashboard": "technician_dashboard",
    "helpdesk_pages.secretary_pages.dashboard": "secretary_dashboard",
    "helpdesk_pages.department_pages.tickets": "department_head_dashboard",
    "helpdesk_pages.department_pages.reports": "department_head_reports",
    "helpdesk_pages.user_pages.my_tickets": "user_my_tickets",
    "helpdesk_pages.user_pages.create_ticket": "user_create_ticket",
    # Admin: índice de reportes de inventario
    "helpdesk_pages.admin_pages.inventory_reports": "admin_inventory_reports",
    # Landing / brand link
    "helpdesk_pages.home": "home_landing",
}


def _is_migrated(active_page: str | None) -> bool:
    return bool(active_page) and active_page in HD_PAGE_MODULES


def _endpoint_is_boostable(endpoint: str | None) -> bool:
    """True si el link del nav apunta a una página migrada (debe llevar hx-boost)."""
    if not HTMX_BOOST_ENABLED or not endpoint:
        return False
    return _is_migrated(ENDPOINT_TO_ACTIVE_PAGE.get(endpoint))


# ---------------------------------------------------------------------------
# Boost por URL (para enlaces de CONTENIDO helpdesk→helpdesk, no del nav).
# Contraparte por-URL de _endpoint_is_boostable: dado el `href` final de un <a>
# (la URL que ya tiene el template, no un endpoint Flask), decide si esa página
# está migrada (registrada en HD_PAGE_MODULES) y debe navegar con morph.
# La usa el filtro Jinja hd_boost(url) (itcj2/templates.py).
# ---------------------------------------------------------------------------

# Rutas de páginas migradas que NO son endpoints de navegación (nunca aparecen
# como link del navbar, así que no viven en ENDPOINT_TO_ACTIVE_PAGE) pero SÍ son
# páginas registradas en HD_PAGE_MODULES a las que se navega desde botones de
# CONTENIDO (ticket_card → detalle, quick-view → detalle de item/campaña…).
# Se listan aquí para que is_boostable_url() (y hd_boost) las reconozca. El valor
# es el hd_page destino (clave de HD_PAGE_MODULES); la URL usa placeholders {x}.
_EXTRA_PAGE_URLS: dict[str, str] = {
    "/help-desk/user/tickets/{ticket_id}": "user_ticket_detail",
    "/help-desk/inventory/items/{item_id}": "inventory_items_item_detail",
    "/help-desk/inventory/campaigns/{campaign_id}": "inventory_campaigns_campaign_detail",
    "/help-desk/inventory/campaigns/{campaign_id}/validate": "inventory_campaigns_campaign_validate",
    "/help-desk/inventory/retirement-requests/{request_id}": "inventory_retirement_retirement_request_detail",
    "/help-desk/inventory/groups/{group_id}": "inventory_groups_group_detail",
}


def _url_template_to_regex(template: str) -> "re.Pattern[str]":
    """Convierte una plantilla de URL con placeholders {x} en un regex que matchea
    una URL concreta (sin query/fragment): '/a/{id}' -> ^/a/[^/]+$."""
    parts = re.split(r"\{[^}]+\}", template)
    body = "[^/]+".join(re.escape(p) for p in parts)
    return re.compile("^" + body + "$")


_BOOSTABLE_URL_TEMPLATES: list[tuple[str, str]] | None = None
_BOOSTABLE_URL_PATTERNS: list[tuple["re.Pattern[str]", str]] | None = None


def _boostable_url_templates() -> list[tuple[str, str]]:
    """(url_template, hd_page) de las páginas migradas, construida perezosamente
    reutilizando ENDPOINT_TO_ACTIVE_PAGE (+ ENDPOINT_MAP para la URL) y
    _EXTRA_PAGE_URLS. Ordena las URLs literales antes que las de placeholder
    (match exacto gana) y, dentro de cada grupo, las más específicas primero."""
    global _BOOSTABLE_URL_TEMPLATES
    if _BOOSTABLE_URL_TEMPLATES is None:
        pairs: dict[str, str] = {}
        for endpoint, hd_page in ENDPOINT_TO_ACTIVE_PAGE.items():
            url_tmpl = ENDPOINT_MAP.get(endpoint)
            if url_tmpl and url_tmpl != "#":
                pairs.setdefault(url_tmpl, hd_page)
        for url_tmpl, hd_page in _EXTRA_PAGE_URLS.items():
            pairs.setdefault(url_tmpl, hd_page)
        _BOOSTABLE_URL_TEMPLATES = sorted(
            pairs.items(), key=lambda kv: ("{" in kv[0], -kv[0].count("/"))
        )
    return _BOOSTABLE_URL_TEMPLATES


def _boostable_url_patterns() -> list[tuple["re.Pattern[str]", str]]:
    """(regex_url, hd_page) de las páginas migradas (ver _boostable_url_templates)."""
    global _BOOSTABLE_URL_PATTERNS
    if _BOOSTABLE_URL_PATTERNS is None:
        _BOOSTABLE_URL_PATTERNS = [
            (_url_template_to_regex(u), p) for u, p in _boostable_url_templates()
        ]
    return _BOOSTABLE_URL_PATTERNS


# Metacaracteres a escapar para un RegExp de JS. NO se usa re.escape porque
# escapa '-' como '\-', que en JS solo vale por Annex B (y es error con flag 'u');
# las URLs de helpdesk llevan guion ("/help-desk/"), así que importa.
_JS_RE_SPECIAL = re.compile(r"[.*+?^${}()|\[\]\\/]")


def _js_url_regex(template: str) -> str:
    """'/a/{id}' -> '^\\/a\\/[^/]+$' (fuente de RegExp válida en JS)."""
    parts = re.split(r"\{[^}]+\}", template)
    body = "[^/]+".join(
        _JS_RE_SPECIAL.sub(lambda m: "\\" + m.group(0), p) for p in parts
    )
    return "^" + body + "$"


def boost_urls_regex() -> str:
    """Alternación regex de las URLs MIGRADAS, para el cliente (data-hd-boost-urls).

    base.js la usa como whitelist ESTRICTA: un destino que no matchea navega
    clásico (recarga). Sin esto el cliente solo sabía ``/^\\/help-desk\\//``, que
    incluye páginas NO migradas (admin/categories, inventory/reports/*) — morfear
    hacia ellas las deja sin su JS.
    """
    if not HTMX_BOOST_ENABLED:
        return ""
    return "|".join(_js_url_regex(tmpl) for tmpl, _ in _boostable_url_templates())


def _url_to_hd_page(url: str) -> str | None:
    """Resuelve una URL helpdesk concreta → su hd_page (o None). Ignora query y
    fragment. Contraparte por-URL de ENDPOINT_TO_ACTIVE_PAGE.get(endpoint)."""
    if not url:
        return None
    path = url.split("#", 1)[0].split("?", 1)[0]
    for pattern, hd_page in _boostable_url_patterns():
        if pattern.match(path):
            return hd_page
    return None


def is_boostable_url(url: str) -> bool:
    """True si ``url`` apunta a una página de Help-Desk migrada (registrada en
    HD_PAGE_MODULES) y el boost está activo.

    Contraparte por-URL de ``_endpoint_is_boostable`` (mismo criterio
    ``_is_migrated``, misma data: ENDPOINT_TO_ACTIVE_PAGE + HD_PAGE_MODULES +
    ENDPOINT_MAP para resolver la URL). Pura e importable; la usa el filtro Jinja
    ``hd_boost(url)`` para decidir si un <a href> de contenido lleva hx-boost.
    """
    if not HTMX_BOOST_ENABLED or not url:
        return False
    return _is_migrated(_url_to_hd_page(url))


def _module_url(path: str) -> str:
    """URL final de un módulo: CDN tal cual; estático local versionado con sv()."""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"/static/helpdesk/{path}?v={sv('helpdesk', path)}"


def _hd_modules_attr(hd_page: str | None) -> str:
    """Valor de data-hd-modules: URLs de los módulos de la página separadas por '|'."""
    return "|".join(_module_url(p) for p in HD_PAGE_MODULES.get(hd_page or "", []))


def _template_to_key(template: str) -> str:
    """Clave única (hd_page) derivada del path del template.

    "helpdesk/inventory/items/item_detail.html" -> "inventory_items_item_detail".
    Para piloto/almacén coincide con el nombre histórico de active_page
    ("helpdesk/admin/home.html" -> "admin_home").
    """
    key = template or ""
    if key.startswith("helpdesk/"):
        key = key[len("helpdesk/"):]
    if key.endswith(".html"):
        key = key[:-5]
    return key.replace("/", "_")


# Alias retrocompatible (algún código/test puede referenciarlo).
HTMX_PILOT_PAGES = set(HD_PAGE_MODULES)


def _build_helpdesk_nav(user_id: int, current_path: str) -> dict:
    """Construye el contexto de navegación de Help-Desk para un usuario.

    Equivale al context_processor ``inject_helpdesk_nav()`` de Flask:
    genera los items de navegación filtrados por permisos y añade la
    URL resuelta a cada item (usando ENDPOINT_MAP en lugar de url_for).
    """
    try:
        from itcj2.apps.helpdesk.utils.navigation import get_helpdesk_navigation
        from itcj2.core.services.authz_service import (
            get_user_permissions_for_app,
            user_roles_in_app,
        )
        from itcj2.database import SessionLocal

        _db = SessionLocal()
        try:
            user_perms = get_user_permissions_for_app(_db, user_id, "helpdesk")
            user_roles = set(user_roles_in_app(_db, user_id, "helpdesk"))
            from itcj2.apps.helpdesk.utils.warehouse_auth import get_warehouse_perms_via_helpdesk
            user_perms = user_perms | get_warehouse_perms_via_helpdesk(_db, user_id)
        finally:
            _db.close()
        nav_items = get_helpdesk_navigation(user_perms, user_roles)

        def _path_only(url: str) -> str:
            """Path sin fragment ni query, para comparar contra request.url.path."""
            return (url or "").split("#", 1)[0].split("?", 1)[0]

        for item in nav_items:
            item["hx_boost"] = _endpoint_is_boostable(item.get("endpoint"))
            item["is_active"] = False
            if item.get("endpoint") and item["endpoint"] != "#":
                item["url"] = ENDPOINT_MAP.get(item["endpoint"], "#")
                if "fragment" in item:
                    item["url"] += item["fragment"]
                if item["url"] != "#":
                    item["is_active"] = _path_only(item["url"]) == current_path

            any_sub_active = False
            for sub in item.get("dropdown", []):
                sub["hx_boost"] = _endpoint_is_boostable(sub.get("endpoint"))
                sub["is_active"] = False
                if sub.get("endpoint") and sub["endpoint"] != "#":
                    sub["url"] = ENDPOINT_MAP.get(sub["endpoint"], "#")
                    if "fragment" in sub:
                        sub["url"] += sub["fragment"]
                    if sub["url"] != "#" and _path_only(sub["url"]) == current_path:
                        any_sub_active = True
                        # Items con fragment (tabs de Config) comparten path: el tab
                        # activo es client-side, así que no resaltamos el sub-item
                        # individual, solo el grupo. Sin fragment sí resalta.
                        sub["is_active"] = "fragment" not in sub

                for sub_sub in sub.get("submenu", []):
                    if sub_sub.get("endpoint") and sub_sub["endpoint"] != "#":
                        sub_sub["url"] = ENDPOINT_MAP.get(sub_sub["endpoint"], "#")

            # Grupo (dropdown) activo si la ruta actual cae en alguno de sus sub-items.
            item["group_active"] = bool(item.get("dropdown")) and any_sub_active

    except Exception as exc:
        logger.warning("Error building helpdesk nav for user %s: %s", user_id, exc)
        nav_items = []

    return {
        "helpdesk_nav_items": nav_items,
        "current_route": current_path,
    }


def render_helpdesk(
    request: Request,
    template: str,
    context: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Renderiza un template de Help-Desk inyectando la navegación automáticamente.

    Equivale a ``render_template()`` de Flask dentro del blueprint de
    Help-Desk, donde el context_processor ``inject_helpdesk_nav()``
    inyectaba los items de navegación en cada respuesta.
    """
    user = getattr(request.state, "current_user", None)

    nav_ctx = (
        _build_helpdesk_nav(int(user["sub"]), request.url.path)
        if user
        else {"helpdesk_nav_items": [], "current_route": request.url.path}
    )

    from .origins import build_origins, origin_for_page

    hd_page = _template_to_key(template)
    ctx = {
        **(context or {}),
        **nav_ctx,
        "hd_page": hd_page,
        "htmx_boost_enabled": HTMX_BOOST_ENABLED and _is_migrated(hd_page),
        "hd_modules": _hd_modules_attr(hd_page),
        "hd_boost_urls": boost_urls_regex(),
        # Registro de orígenes del botón "Volver" (pages/origins.py). Se serializa
        # una vez en el shell y lo lee HelpdeskUtils.initBackButton().
        "hd_origins": build_origins(),
        "hd_origin_self": origin_for_page(hd_page) or "",
        # Id del usuario actual, expuesto en [data-hd-page] como data-current-user-id
        # (base_helpdesk.html). Lo lee window.__hdIsOwnEvent (sockets/helpdesk_client.js)
        # para que el cliente ignore el eco de sus propios broadcasts de socket.
        "hd_current_user_id": int(user["sub"]) if user else None,
    }
    return render(request, template, ctx, status_code)
