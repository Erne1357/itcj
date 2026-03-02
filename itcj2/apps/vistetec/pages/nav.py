"""
Helper de navegación y renderizado para páginas de VisteTec.

``render_vistetec()`` es el equivalente FastAPI del context_processor
``inject_vistetec_nav()`` de Flask: inyecta automáticamente
``vistetec_nav_items``, ``current_route`` y ``user_roles`` en cada página.
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import HTMLResponse

from itcj2.templates import ENDPOINT_MAP, render

logger = logging.getLogger("itcj2.apps.vistetec.pages")

# Estructura completa de navegación indexada por rol
_NAV_BY_ROLE: dict[str, list[dict]] = {
    "student": [
        {"label": "Catálogo",      "endpoint": "vistetec_pages.student_pages.catalog",          "icon": "bi-grid-3x3-gap"},
        {"label": "Mis Apartados", "endpoint": "vistetec_pages.student_pages.my_appointments",  "icon": "bi-calendar-check"},
        {"label": "Mis Donaciones","endpoint": "vistetec_pages.student_pages.my_donations",     "icon": "bi-heart"},
    ],
    "volunteer": [
        {"label": "Dashboard",          "endpoint": "vistetec_pages.volunteer_pages.dashboard",         "icon": "bi-speedometer2"},
        {"label": "Citas",              "endpoint": "vistetec_pages.volunteer_pages.appointments",      "icon": "bi-calendar2-week"},
        {"label": "Registrar Prenda",   "endpoint": "vistetec_pages.volunteer_pages.garment_form",      "icon": "bi-plus-circle"},
        {"label": "Registrar Donación", "endpoint": "vistetec_pages.volunteer_pages.register_donation", "icon": "bi-gift"},
    ],
    "admin": [
        {"label": "Dashboard Admin", "endpoint": "vistetec_pages.admin_pages.dashboard", "icon": "bi-speedometer"},
        {"label": "Prendas",         "endpoint": "vistetec_pages.admin_pages.garments",  "icon": "bi-tag"},
        {"label": "Despensa",        "endpoint": "vistetec_pages.admin_pages.pantry",    "icon": "bi-box-seam"},
        {"label": "Campañas",        "endpoint": "vistetec_pages.admin_pages.campaigns", "icon": "bi-megaphone"},
        {"label": "Reportes",        "endpoint": "vistetec_pages.admin_pages.reports",   "icon": "bi-graph-up"},
    ],
}


def _build_vistetec_nav(user_id: int) -> tuple[list[dict], set[str]]:
    """Construye nav items y roles para un usuario de VisteTec.

    Retorna ``(nav_items, user_roles)`` — ambos inyectados en el contexto
    del template, igual que el context_processor de Flask.
    """
    try:
        from itcj2.core.services.authz_service import user_roles_in_app

        user_roles = set(user_roles_in_app(user_id, "vistetec"))
        nav_items: list[dict] = []

        for role in ("student", "volunteer", "admin"):
            if role in user_roles:
                for item in _NAV_BY_ROLE[role]:
                    entry = {**item, "url": ENDPOINT_MAP.get(item["endpoint"], "#")}
                    nav_items.append(entry)

    except Exception as exc:
        logger.warning("Error building vistetec nav for user %s: %s", user_id, exc)
        nav_items = []
        user_roles = set()

    return nav_items, user_roles


def render_vistetec(
    request: Request,
    template: str,
    context: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Renderiza un template de VisteTec inyectando la navegación automáticamente.

    Equivale a ``render_template()`` de Flask dentro del blueprint
    ``vistetec_pages_bp``, donde el context_processor ``inject_vistetec_nav()``
    inyectaba ``vistetec_nav_items``, ``current_route`` y ``user_roles``.
    """
    user = getattr(request.state, "current_user", None)

    if user:
        nav_items, user_roles = _build_vistetec_nav(int(user["sub"]))
    else:
        nav_items, user_roles = [], set()

    ctx = {
        **(context or {}),
        "vistetec_nav_items": nav_items,
        "current_route": request.url.path,
        "user_roles": user_roles,
    }
    return render(request, template, ctx, status_code)
