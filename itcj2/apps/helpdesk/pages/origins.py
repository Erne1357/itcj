"""Registro canónico de orígenes de navegación del helpdesk.

Fuente única de verdad para el botón "Volver" de las páginas de detalle
(ticket e ítem de inventario). Antes cada página resolvía su destino con un
`switch` propio en JS: `ticket_detail.js` tenía ocho casos —cuatro de ellos
apuntando a rutas inexistentes— e `item_detail.js` una segunda implementación
divergente sobre el mismo contrato de ids.

Cada slug se declara aquí con su URL tomada de `ENDPOINT_MAP`, de modo que un
destino renombrado se detecta en el arranque (y en `test_origins.py`) en vez de
degradar en silencio a `href="#"`.

El registro se serializa en `base_helpdesk.html` y lo consume
`HelpdeskUtils.initBackButton()`.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# Slug -> (endpoint de ENDPOINT_MAP, etiqueta, icono FA).
# El endpoint es la clave estilo Flask que ya usa el shim `url_for` del proyecto;
# resolver desde ahí evita que este registro se desincronice de la tabla real de
# rutas.
_ORIGIN_DEFS: dict[str, tuple[str, str, str]] = {
    "my_tickets":             ("helpdesk_pages.user_pages.my_tickets",          "Mis Tickets",           "fa-ticket"),
    "technician":             ("helpdesk_pages.technician_pages.dashboard",     "Panel de Técnicos",     "fa-screwdriver-wrench"),
    "admin_tickets_list":     ("helpdesk_pages.admin_pages.tickets_list",       "Lista de Tickets",      "fa-list"),
    "admin_home":             ("helpdesk_pages.admin_pages.home",               "Dashboard",             "fa-gauge"),
    "secretary":              ("helpdesk_pages.secretary_pages.dashboard",      "Dashboard Secretaría",  "fa-clipboard-list"),
    "assign":                 ("helpdesk_pages.admin_pages.assign_tickets",     "Asignar Tickets",       "fa-user-plus"),
    "department":             ("helpdesk_pages.department_pages.tickets",       "Departamento",          "fa-building"),
    "stats":                  ("helpdesk_pages.admin_pages.stats",              "Estadísticas",          "fa-chart-column"),
    "analysis":               ("helpdesk_pages.admin_pages.analysis",           "Análisis",              "fa-chart-line"),
    "inventory_items":        ("helpdesk_pages.inventory_pages.items_list",     "Inventario",            "fa-laptop"),
    "inventory_verification": ("helpdesk_pages.inventory_pages.verification",   "Verificación",          "fa-clipboard-check"),
    "inventory_assign":       ("helpdesk_pages.inventory_pages.assign_equipment", "Asignar Equipos",     "fa-people-arrows"),
}

# Slugs históricos que siguen llegando por notificaciones ya enviadas.
# `secretary` cambia de destino a propósito: hoy resuelve a `/admin/assign-tickets`
# (`ticket_detail.js:197-200`), que contradice su propio nombre.
_ORIGIN_ALIASES: dict[str, str] = {
    "secretary_dashboard": "secretary",
    "admin": "admin_tickets_list",
    "dashboard": "my_tickets",
}

# `hd_page` de la página de partida -> slug de origen. Cubre TODAS las claves de
# `HD_PAGE_MODULES`, no solo las doce con slug propio: las páginas sin destino
# natural mapean al slug de su sección para que ningún origen quede sin resolver.
HD_PAGE_TO_ORIGIN: dict[str, str] = {
    # Tickets
    "user_my_tickets":                "my_tickets",
    "user_create_ticket":             "my_tickets",
    "user_ticket_detail":             "my_tickets",
    "technician_dashboard":           "technician",
    "secretary_dashboard":            "secretary",
    "department_head_dashboard":      "department",
    "department_head_reports":        "department",
    "admin_tickets_list":             "admin_tickets_list",
    "admin_assign_tickets":           "assign",
    # Admin / reportes
    "admin_home":                     "admin_home",
    "admin_config":                   "admin_home",
    "admin_documents":                "admin_home",
    "admin_inventory_reports":        "admin_home",
    "home_landing":                   "admin_home",
    "admin_stats":                    "stats",
    "admin_analysis":                 "analysis",
    # Inventario
    "inventory_items_items_list":     "inventory_items",
    "inventory_items_item_create":    "inventory_items",
    "inventory_items_item_detail":    "inventory_items",
    "inventory_items_pending_items":  "inventory_items",
    "inventory_dashboard":            "inventory_items",
    "inventory_groups_groups_list":   "inventory_items",
    "inventory_groups_group_detail":  "inventory_items",
    "inventory_campaigns_campaigns_list":            "inventory_items",
    "inventory_campaigns_campaign_create":           "inventory_items",
    "inventory_campaigns_campaign_detail":           "inventory_items",
    "inventory_campaigns_campaign_validate":         "inventory_items",
    "inventory_retirement_retirement_requests_list": "inventory_items",
    "inventory_retirement_retirement_request_create": "inventory_items",
    "inventory_retirement_retirement_request_detail": "inventory_items",
    "inventory_reports_reports":      "inventory_items",
    "inventory_reports_lifecycle":    "inventory_items",
    "inventory_reports_maintenance":  "inventory_items",
    "inventory_reports_warranty":     "inventory_items",
    "inventory_reports_verification": "inventory_verification",
    "inventory_assignment_assign_equipment": "inventory_assign",
    "inventory_assignment_my_equipment":     "inventory_assign",
    # Almacén: no tiene detalle propio al que volver; cae al tablero de tickets.
    "warehouse_dashboard":            "admin_home",
    "warehouse_categories":           "admin_home",
    "warehouse_products":             "admin_home",
    "warehouse_entries":              "admin_home",
    "warehouse_movements":            "admin_home",
    "warehouse_reports":              "admin_home",
}


def _endpoint_map() -> dict[str, str]:
    # Import perezoso: `itcj2.templates` resuelve `pages.nav` en runtime, así que
    # un import de nivel superior en ambos sentidos cerraría el ciclo.
    from itcj2.templates import ENDPOINT_MAP

    return ENDPOINT_MAP


def build_origins() -> dict[str, dict[str, str]]:
    """Slug -> {url, label, icon}, con la URL resuelta desde ENDPOINT_MAP.

    Un endpoint ausente se omite y se registra: mejor un botón que cae al default
    que uno que apunta a `#`.
    """
    endpoint_map = _endpoint_map()
    origins: dict[str, dict[str, str]] = {}
    for slug, (endpoint, label, icon) in _ORIGIN_DEFS.items():
        url = endpoint_map.get(endpoint)
        if not url:
            logger.warning("origen '%s' apunta a un endpoint inexistente: %s", slug, endpoint)
            continue
        origins[slug] = {"url": url, "label": label, "icon": icon}
    return origins


def resolve_origin(slug: str | None) -> dict[str, str] | None:
    """Resuelve un slug (o alias) a su entrada. Desconocido -> None."""
    if not slug:
        return None
    origins = build_origins()
    return origins.get(_ORIGIN_ALIASES.get(slug, slug))


def origin_for_page(hd_page: str | None) -> str | None:
    """Slug de origen que corresponde a la página desde la que se navega."""
    if not hd_page:
        return None
    return HD_PAGE_TO_ORIGIN.get(hd_page)


def origin_qs(slug: str | None, prefix: str = "?") -> str:
    """`?from=slug` si el slug resuelve; cadena vacía si no."""
    if not slug or resolve_origin(slug) is None:
        return ""
    return f"{prefix}from={_ORIGIN_ALIASES.get(slug, slug)}"
