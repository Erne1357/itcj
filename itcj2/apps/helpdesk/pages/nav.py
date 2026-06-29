"""
Helpers de navegación y renderizado para páginas de Help-Desk.

``render_helpdesk()`` es el equivalente FastAPI del context_processor
``inject_helpdesk_nav()`` de Flask: inyecta automáticamente
``helpdesk_nav_items`` y ``current_route`` en cada página de la app.
"""
from __future__ import annotations

import logging

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
    "admin_home": ["js/admin/home.js"],
    "admin_tickets_list": ["js/admin/tickets_list.js"],
    "admin_categories": [],
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
}

# Mapa endpoint de nav (estilo Flask) -> hd_page destino. Permite saber si un
# link del nav apunta a una página migrada (y por tanto debe boostearse). El
# valor es el hd_page (clave única por template) de la página destino.
ENDPOINT_TO_ACTIVE_PAGE: dict[str, str] = {
    "helpdesk_pages.admin_pages.home": "admin_home",
    "helpdesk_pages.admin_pages.tickets_list": "admin_tickets_list",
    "helpdesk_pages.admin_pages.categories": "admin_categories",
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
    "helpdesk_pages.inventory_pages.pending_items": "inventory_items_pending_items",
    "helpdesk_pages.inventory_pages.groups_list": "inventory_groups_groups_list",
    "helpdesk_pages.inventory_pages.dashboard": "inventory_dashboard",
    "helpdesk_pages.inventory_pages.assign_equipment": "inventory_assignment_assign_equipment",
    "helpdesk_pages.inventory_pages.my_equipment": "inventory_assignment_my_equipment",
    "helpdesk_pages.inventory_pages.verification": "inventory_reports_verification",
    "helpdesk_pages.inventory_pages.reports": "inventory_reports_reports",
}


def _is_migrated(active_page: str | None) -> bool:
    return bool(active_page) and active_page in HD_PAGE_MODULES


def _endpoint_is_boostable(endpoint: str | None) -> bool:
    """True si el link del nav apunta a una página migrada (debe llevar hx-boost)."""
    if not HTMX_BOOST_ENABLED or not endpoint:
        return False
    return _is_migrated(ENDPOINT_TO_ACTIVE_PAGE.get(endpoint))


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

        for item in nav_items:
            item["hx_boost"] = _endpoint_is_boostable(item.get("endpoint"))
            if item.get("endpoint") and item["endpoint"] != "#":
                item["url"] = ENDPOINT_MAP.get(item["endpoint"], "#")
                if "fragment" in item:
                    item["url"] += item["fragment"]

            for sub in item.get("dropdown", []):
                sub["hx_boost"] = _endpoint_is_boostable(sub.get("endpoint"))
                if sub.get("endpoint") and sub["endpoint"] != "#":
                    sub["url"] = ENDPOINT_MAP.get(sub["endpoint"], "#")
                    if "fragment" in sub:
                        sub["url"] += sub["fragment"]

                for sub_sub in sub.get("submenu", []):
                    if sub_sub.get("endpoint") and sub_sub["endpoint"] != "#":
                        sub_sub["url"] = ENDPOINT_MAP.get(sub_sub["endpoint"], "#")

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

    hd_page = _template_to_key(template)
    ctx = {
        **(context or {}),
        **nav_ctx,
        "hd_page": hd_page,
        "htmx_boost_enabled": HTMX_BOOST_ENABLED and _is_migrated(hd_page),
        "hd_modules": _hd_modules_attr(hd_page),
    }
    return render(request, template, ctx, status_code)
