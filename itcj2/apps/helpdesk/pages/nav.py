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

from itcj2.templates import ENDPOINT_MAP, render

logger = logging.getLogger("itcj2.apps.helpdesk.pages")


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

        user_perms = get_user_permissions_for_app(user_id, "helpdesk")
        user_roles = set(user_roles_in_app(user_id, "helpdesk"))
        nav_items = get_helpdesk_navigation(user_perms, user_roles)

        for item in nav_items:
            if item.get("endpoint") and item["endpoint"] != "#":
                item["url"] = ENDPOINT_MAP.get(item["endpoint"], "#")
                if "fragment" in item:
                    item["url"] += item["fragment"]

            for sub in item.get("dropdown", []):
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

    ctx = {**(context or {}), **nav_ctx}
    return render(request, template, ctx, status_code)
