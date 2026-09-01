"""Navegación y renderizado de las páginas de Prórrogas.

``render_prorrogas_tec()`` inyecta ``prorrogas_tec_nav_items`` en cada página,
como hacía el context_processor del blueprint de Flask.

Usa el ``render()`` global de :mod:`itcj2.templates` (no una instancia propia de
Jinja2Templates como titulatec), así que el directorio de templates de esta app
tiene que estar en el searchpath de ese módulo.
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import HTMLResponse

from itcj2.templates import ENDPOINT_MAP, render

logger = logging.getLogger("itcj2.apps.prorrogas_tec.pages")


def _build_prorrogas_tec_nav(user_id: int) -> list[dict]:
    """Construye los items de navegación de Prórrogas para un usuario.

    - Alumnos: nav fija de estudiante.
    - Resto: nav de administración.
    """
    try:
        from itcj2.apps.prorrogas_tec.utils.period_utils import is_student_window_open
        from itcj2.core.services.authz_service import (
            get_user_permissions_for_app,
            user_roles_in_app,
        )
        from itcj2.database import SessionLocal

        _db = SessionLocal()
        try:
            prorrogas_roles = set(user_roles_in_app(_db, user_id, "prorrogas_tec"))
            student_open = is_student_window_open()

            if "student" in prorrogas_roles:
                nav_items = [
                    {
                        "label": "Inicio",
                        "endpoint": "prorrogas_tec_pages.student_pages.student_home",
                        "icon": "bi-house",
                    },
                    {
                        "label": "Mis solicitudes",
                        "endpoint": "prorrogas_tec_pages.student_pages.student_requests",
                        "icon": "bi-journal-text",
                    },
                ]
            else:
                user_perms = get_user_permissions_for_app(_db, user_id, "prorrogas_tec")
                nav_items = _get_prorrogas_navigation(user_perms, student_open)
            
        finally:
            _db.close()

        for item in nav_items:
            if item.get("endpoint"):
                item["url"] = ENDPOINT_MAP.get(item["endpoint"], "#")

    except Exception as exc:
        logger.warning("Error building prorrogas nav for user %s: %s", user_id, exc)
        nav_items = []

    return nav_items


def _get_prorrogas_navigation(user_permissions: set, student_window_open: bool) -> list[dict]:
    """Nav de administración.

    TODO(prorrogas): hoy NO filtra por permisos —devuelve `full_nav` entero—, así
    que la nav enseña enlaces que el guard del router rechazará con 403. Los
    códigos de `permission` ya apuntan a los permisos que siembra
    `database/DML/prorrogas_tec/`; falta cablear el filtro. Ver docs/PENDIENTES.md
    """
    full_nav = [
        # Admin
        {"label": "Dashboard Administrador","endpoint": "prorrogas_tec_pages.admin_pages.admin_home",   "permission": "prorrogas_tec.dashboard.page.view",  "icon": "bi-bar-chart-fill"},
        # {"label": "Usuarios",     "endpoint": "agendatec_pages.admin_pages.admin_users",              "permission": "agendatec.users.page.list",             "icon": "bi-people"},
        {"label": "Solicitudes",  "endpoint": "prorrogas_tec_pages.admin_pages.admin_requests",         "permission": "prorrogas_tec.requests.page.list",   "icon": "bi-clipboard-data"},
        # {"label": "Crear Solicitud","endpoint": "agendatec_pages.admin_pages.admin_create_request",   "permission": "agendatec.requests.page.create",        "icon": "bi-plus-circle"},
        {"label": "Períodos",     "endpoint": "prorrogas_tec_pages.admin_pages.admin_periods",          "permission": "prorrogas_tec.periods.page.list", "icon": "bi-calendar-check"},
    ]
    return [item for item in full_nav ]


def render_prorrogas_tec(
    request: Request,
    template: str,
    context: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Renderiza un template de Prórrogas inyectando la navegación."""
    user = getattr(request.state, "current_user", None)
    nav_items = _build_prorrogas_tec_nav(int(user["sub"])) if user else []
    ctx = {**(context or {}), "prorrogas_tec_nav_items": nav_items}
    return render(request, template, ctx, status_code)
