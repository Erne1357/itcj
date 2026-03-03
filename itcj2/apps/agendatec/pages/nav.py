"""
Helper de navegación y renderizado para páginas de AgendaTec.

``render_agendatec()`` es el equivalente FastAPI del context_processor
``inject_agendatec_nav()`` de Flask: inyecta automáticamente
``agendatec_nav_items`` en cada página de la app.
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import HTMLResponse

from itcj2.templates import ENDPOINT_MAP, render

logger = logging.getLogger("itcj2.apps.agendatec.pages")


def _build_agendatec_nav(user_id: int) -> list[dict]:
    """Construye los items de navegación de AgendaTec para un usuario.

    Replica la lógica de ``inject_agendatec_nav()`` de Flask:
    - Estudiantes con ventana abierta: nav fija de estudiante.
    - Resto: nav filtrada por permisos (coordinador, admin, social).
    """
    try:
        from itcj2.apps.agendatec.utils.period_utils import is_student_window_open
        from itcj2.core.services.authz_service import (
            get_user_permissions_for_app,
            user_roles_in_app,
        )
        from itcj2.database import SessionLocal

        _db = SessionLocal()
        try:
            agendatec_roles = set(user_roles_in_app(_db, user_id, "agendatec"))
            student_open = is_student_window_open()

            if "student" in agendatec_roles and student_open:
                nav_items = [
                    {
                        "label": "Inicio",
                        "endpoint": "agendatec_pages.student_pages.student_home",
                        "icon": "bi-house",
                    },
                    {
                        "label": "Mis solicitudes",
                        "endpoint": "agendatec_pages.student_pages.student_requests",
                        "icon": "bi-journal-text",
                    },
                ]
            else:
                user_perms = get_user_permissions_for_app(_db, user_id, "agendatec")
                nav_items = _get_agendatec_navigation(user_perms, student_open)
        finally:
            _db.close()

        for item in nav_items:
            if item.get("endpoint"):
                item["url"] = ENDPOINT_MAP.get(item["endpoint"], "#")

    except Exception as exc:
        logger.warning("Error building agendatec nav for user %s: %s", user_id, exc)
        nav_items = []

    return nav_items


def _get_agendatec_navigation(user_permissions: set, student_window_open: bool) -> list[dict]:
    """Devuelve la navegación filtrada por permisos (equivalente a get_agendatec_navigation)."""
    full_nav = [
        # Coordinador
        {"label": "Dashboard",    "endpoint": "agendatec_pages.coord_pages.coord_home_page",         "permission": "agendatec.coord_dashboard.page.view",  "icon": "bi-speedometer2"},
        {"label": "Horario",      "endpoint": "agendatec_pages.coord_pages.coord_slots_page",         "permission": "agendatec.slots.page.list",             "icon": "bi-calendar-week"},
        {"label": "Citas del día","endpoint": "agendatec_pages.coord_pages.coord_appointments_page",  "permission": "agendatec.appointments.page.list",      "icon": "bi-calendar-event"},
        {"label": "Bajas",        "endpoint": "agendatec_pages.coord_pages.coord_drops_page",         "permission": "agendatec.drops.page.list",             "icon": "bi-person-dash"},
        # Admin
        {"label": "Dashboard Admin","endpoint": "agendatec_pages.admin_pages.admin_home",             "permission": "agendatec.admin_dashboard.page.view",  "icon": "bi-bar-chart-fill"},
        {"label": "Usuarios",     "endpoint": "agendatec_pages.admin_pages.admin_users",              "permission": "agendatec.users.page.list",             "icon": "bi-people"},
        {"label": "Solicitudes",  "endpoint": "agendatec_pages.admin_pages.admin_requests",           "permission": "agendatec.requests.page.list",          "icon": "bi-clipboard-data"},
        {"label": "Crear Solicitud","endpoint": "agendatec_pages.admin_pages.admin_create_request",   "permission": "agendatec.requests.page.create",        "icon": "bi-plus-circle"},
        {"label": "Reportes",     "endpoint": "agendatec_pages.admin_pages.admin_reports",            "permission": "agendatec.reports.page.view",           "icon": "bi-graph-up"},
        {"label": "Encuestas",    "endpoint": "agendatec_pages.admin_surveys_pages.admin_surveys",    "permission": "agendatec.surveys.page.list",           "icon": "bi-list-check"},
        {"label": "Períodos",     "endpoint": "agendatec_pages.admin_pages.admin_periods",            "permission": "agendatec.periods.page.list",           "icon": "bi-calendar-check"},
        # Servicio Social
        {"label": "Citas",        "endpoint": "agendatec_pages.social_pages.social_home",             "permission": "agendatec.social.page.home",            "icon": "bi-calendar-heart"},
    ]
    return [item for item in full_nav if item["permission"] in user_permissions]


def render_agendatec(
    request: Request,
    template: str,
    context: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Renderiza un template de AgendaTec inyectando la navegación automáticamente.

    Equivale a ``render_template()`` de Flask dentro del blueprint
    ``agendatec_pages_bp``, donde el context_processor ``inject_agendatec_nav()``
    inyectaba los items de navegación en cada respuesta.
    """
    user = getattr(request.state, "current_user", None)
    nav_items = _build_agendatec_nav(int(user["sub"])) if user else []

    ctx = {**(context or {}), "agendatec_nav_items": nav_items}
    return render(request, template, ctx, status_code)
