"""
Configuración de Jinja2 y helpers de renderizado para páginas HTML en FastAPI.

Provee:
- ``render()``: equivalente a ``render_template()`` de Flask con contexto global inyectado.
- ``url_for_compat``: mapeo Flask endpoint → URL para mantener templates sin cambios.
- ``_TemplateRequest``: proxy del Request de Starlette que agrega ``request.path``.
- Equivalentes de los context_processors de Flask: ``nav_for``, ``is_active``, ``active_theme``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .config import get_settings, load_static_manifest

logger = logging.getLogger("itcj2.templates")

# ---------------------------------------------------------------------------
# Configuración de Jinja2 (comparte los mismos templates de Flask)
# ---------------------------------------------------------------------------

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

templates = Jinja2Templates(
    directory=[
        os.path.join(_BASE, "itcj2", "core", "templates"),
        os.path.join(_BASE, "itcj2", "apps", "agendatec", "templates"),
        os.path.join(_BASE, "itcj2", "apps", "helpdesk", "templates"),
        os.path.join(_BASE, "itcj2", "apps", "vistetec", "templates"),
    ]
)

# ---------------------------------------------------------------------------
# Static versioning
# ---------------------------------------------------------------------------

_manifest: dict | None = None


def _get_manifest() -> dict:
    global _manifest
    if _manifest is None:
        _manifest = load_static_manifest()
    return _manifest


def sv(app_name: str, filename: str) -> str:
    """Retorna el hash de un archivo estático (mismo comportamiento que sv() de Flask)."""
    fallback = get_settings().STATIC_VERSION
    return _get_manifest().get(app_name, {}).get(filename, fallback)


# ---------------------------------------------------------------------------
# Flask-compatible request proxy
# ---------------------------------------------------------------------------


class _TemplateRequest:
    """Wrapper del Request de Starlette compatible con templates de Flask.

    Agrega la propiedad ``path`` que Flask expone como ``request.path``.
    Todos los demás atributos se delegan al Request original de Starlette.
    """

    __slots__ = ("_request",)

    def __init__(self, request: Request) -> None:
        object.__setattr__(self, "_request", request)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_request"), name)

    @property
    def path(self) -> str:
        return object.__getattribute__(self, "_request").url.path


# ---------------------------------------------------------------------------
# Mapa de endpoints Flask → URLs absolutas
#
# Permite que los templates usen url_for('endpoint_name') sin modificaciones.
# Las URLs coinciden con las rutas reales del proyecto (iguales en Flask y FastAPI).
# ---------------------------------------------------------------------------

ENDPOINT_MAP: dict[str, str] = {
    # ── Core: Auth ──────────────────────────────────────────────────────────
    "pages_core.pages_auth.login_page":                  "/itcj/login",

    # ── Core: Dashboard ─────────────────────────────────────────────────────
    "pages_core.pages_dashboard.dashboard":              "/itcj/dashboard",

    # ── Core: Perfil ────────────────────────────────────────────────────────
    "pages_core.pages_profile.profile":                  "/itcj/profile",

    # ── Core: Configuración ─────────────────────────────────────────────────
    "pages_core.pages_config.settings":                  "/itcj/config",
    "pages_core.pages_config.apps_management":           "/itcj/config/apps",
    "pages_core.pages_config.roles_management":          "/itcj/config/roles",
    "pages_core.pages_config.users_management":          "/itcj/config/users",
    "pages_core.pages_config.themes_management":         "/itcj/config/themes",
    "pages_core.pages_config.positions_management":      "/itcj/config/departments",
    "pages_core.pages_config.app_permissions":           "/itcj/config/apps/{app_key}/permissions",
    "pages_core.pages_config.user_detail":               "/itcj/config/users/{user_id}",
    "pages_core.pages_config.department_detail":         "/itcj/config/departments/{department_id}",
    "pages_core.pages_config.position_detail":           "/itcj/config/positions/{position_id}",
    "pages_core.pages_config.email_management":          "/itcj/config/email",
    "pages_core.pages_config.email_auth_login":          "/itcj/config/email/auth/login",
    "pages_core.pages_config.tasks_management":          "/itcj/config/system/tasks",

    # ── Core: Móvil ─────────────────────────────────────────────────────────
    "pages_core.pages_mobile.mobile_dashboard":          "/itcj/m/",
    "pages_core.pages_mobile.mobile_notifications":      "/itcj/m/notifications",
    "pages_core.pages_mobile.mobile_profile":            "/itcj/m/profile",
    "pages_core.pages_mobile.mobile_switch_desktop":     "/itcj/m/switch-desktop",
    "pages_core.pages_mobile.mobile_switch_mobile":      "/itcj/m/switch-mobile",

    # ── Help-Desk: Páginas de usuario ───────────────────────────────────────
    "helpdesk_pages.user_pages.create_ticket":           "/help-desk/user/create",
    "helpdesk_pages.user_pages.my_tickets":              "/help-desk/user/my-tickets",
    "helpdesk_pages.inventory_pages.my_equipment":       "/help-desk/inventory/my-equipment",

    # ── Help-Desk: Dashboards por rol ────────────────────────────────────────
    "helpdesk_pages.secretary_pages.dashboard":          "/help-desk/secretary/",
    "helpdesk_pages.technician_pages.dashboard":         "/help-desk/technician/dashboard",
    "helpdesk_pages.technician_pages.my_assignments":    "/help-desk/technician/my-assignments",
    "helpdesk_pages.technician_pages.team":              "/help-desk/technician/team",
    "helpdesk_pages.department_pages.tickets":           "/help-desk/department/",
    "helpdesk_pages.department_pages.reports":           "/help-desk/department/reports",

    # ── Help-Desk: Páginas de administrador ─────────────────────────────────
    "helpdesk_pages.admin_pages.home":                   "/help-desk/admin/home",
    "helpdesk_pages.admin_pages.assign_tickets":         "/help-desk/admin/assign-tickets",
    "helpdesk_pages.admin_pages.tickets_list":           "/help-desk/admin/tickets-list",
    "helpdesk_pages.admin_pages.categories":             "/help-desk/admin/categories",
    "helpdesk_pages.admin_pages.stats":                  "/help-desk/admin/stats",
    "helpdesk_pages.admin_pages.analysis":               "/help-desk/admin/analysis",
    "helpdesk_pages.admin_pages.documents":              "/help-desk/admin/documents",

    # ── Help-Desk: Almacén (Warehouse) ──────────────────────────────────────
    "helpdesk_pages.warehouse_pages.dashboard":          "/help-desk/warehouse/dashboard",
    "helpdesk_pages.warehouse_pages.products":           "/help-desk/warehouse/products",
    "helpdesk_pages.warehouse_pages.categories":         "/help-desk/warehouse/categories",
    "helpdesk_pages.warehouse_pages.entries":            "/help-desk/warehouse/entries",
    "helpdesk_pages.warehouse_pages.movements":          "/help-desk/warehouse/movements",
    "helpdesk_pages.warehouse_pages.reports":            "/help-desk/warehouse/reports",

    # ── Help-Desk: Inventario ────────────────────────────────────────────────
    "helpdesk_pages.inventory_pages.dashboard":          "/help-desk/inventory/dashboard",
    "helpdesk_pages.inventory_pages.items_list":         "/help-desk/inventory/items",
    "helpdesk_pages.inventory_pages.item_create":        "/help-desk/inventory/items/create",
    "helpdesk_pages.inventory_pages.bulk_register":      "/help-desk/inventory/bulk-register",
    "helpdesk_pages.inventory_pages.groups_list":        "/help-desk/inventory/groups",
    "helpdesk_pages.inventory_pages.pending_items":      "/help-desk/inventory/pending",
    "helpdesk_pages.inventory_pages.assign_equipment":   "/help-desk/inventory/assign",
    "helpdesk_pages.inventory_pages.warranty_report":    "/help-desk/inventory/reports/warranty",
    "helpdesk_pages.inventory_pages.maintenance_report": "/help-desk/inventory/reports/maintenance",
    "helpdesk_pages.inventory_pages.lifecycle_report":   "/help-desk/inventory/reports/lifecycle",
    "helpdesk_pages.inventory_pages.verification":                  "/help-desk/inventory/verification",
    "helpdesk_pages.inventory_pages.reports":                       "/help-desk/inventory/reports",
    "helpdesk_pages.inventory_pages.retirement_requests_list":      "/help-desk/inventory/retirement-requests",
    "helpdesk_pages.inventory_pages.retirement_request_create":     "/help-desk/inventory/retirement-requests/create",
    "helpdesk_pages.inventory_pages.retirement_request_detail":     "/help-desk/inventory/retirement-requests/{request_id}",
    "helpdesk_pages.inventory_pages.campaigns_list":                "/help-desk/inventory/campaigns",
    "helpdesk_pages.inventory_pages.campaign_create":               "/help-desk/inventory/campaigns/create",
    "helpdesk_pages.inventory_pages.campaign_detail":               "/help-desk/inventory/campaigns/{campaign_id}",
    "helpdesk_pages.inventory_pages.campaign_validate":             "/help-desk/inventory/campaigns/{campaign_id}/validate",

    # ── AgendaTec: Páginas ───────────────────────────────────────────────────
    # Student
    "agendatec_pages.student_pages.student_home":        "/agendatec/student/home",
    "agendatec_pages.student_pages.student_requests":    "/agendatec/student/requests",
    "agendatec_pages.student_pages.student_new_request": "/agendatec/student/request",
    "agendatec_pages.student_pages.student_close":       "/agendatec/student/close",
    # Coord
    "agendatec_pages.coord_pages.coord_home_page":       "/agendatec/coord/home",
    "agendatec_pages.coord_pages.coord_slots_page":      "/agendatec/coord/slots",
    "agendatec_pages.coord_pages.coord_appointments_page": "/agendatec/coord/appointments",
    "agendatec_pages.coord_pages.coord_drops_page":      "/agendatec/coord/drops",
    # Admin
    "agendatec_pages.admin_pages.admin_home":            "/agendatec/admin/home",
    "agendatec_pages.admin_pages.admin_users":           "/agendatec/admin/users",
    "agendatec_pages.admin_pages.admin_requests":        "/agendatec/admin/requests",
    "agendatec_pages.admin_pages.admin_create_request":  "/agendatec/admin/requests/create",
    "agendatec_pages.admin_pages.admin_reports":         "/agendatec/admin/reports",
    "agendatec_pages.admin_pages.admin_periods":         "/agendatec/admin/periods",
    "agendatec_pages.admin_pages.admin_period_days":     "/agendatec/admin/periods/{period_id}/days",
    # Admin Surveys
    "agendatec_pages.admin_surveys_pages.admin_surveys": "/agendatec/surveys/",
    # Social
    "agendatec_pages.social_pages.social_home":          "/agendatec/social/home",

    # ── AgendaTec: API ───────────────────────────────────────────────────────
    # Periods
    "agendatec_api.api_periods.list_periods":              "/api/agendatec/v2/periods",
    "agendatec_api.api_periods.create_period":             "/api/agendatec/v2/periods",
    "agendatec_api.api_periods.get_active_period":         "/api/agendatec/v2/periods/active",
    "agendatec_api.api_periods.get_period":                "/api/agendatec/v2/periods/{period_id}",
    "agendatec_api.api_periods.update_period":             "/api/agendatec/v2/periods/{period_id}",
    "agendatec_api.api_periods.activate_period":           "/api/agendatec/v2/periods/{period_id}/activate",
    "agendatec_api.api_periods.delete_period":             "/api/agendatec/v2/periods/{period_id}",
    "agendatec_api.api_periods.get_enabled_days":          "/api/agendatec/v2/periods/{period_id}/enabled-days",
    "agendatec_api.api_periods.set_enabled_days":          "/api/agendatec/v2/periods/{period_id}/enabled-days",
    "agendatec_api.api_periods.get_period_stats":          "/api/agendatec/v2/periods/{period_id}/stats",
    # Programs
    "agendatec_api.api_programs.list_programs":            "/api/agendatec/v2/programs",
    # Admin Stats
    "agendatec_api.api_admin.admin_stats.stats_overview":     "/api/agendatec/v2/admin/stats/overview",
    "agendatec_api.api_admin.admin_stats.stats_coordinators": "/api/agendatec/v2/admin/stats/coordinators",
    # Admin Requests
    "agendatec_api.api_admin.admin_requests.admin_list_requests":          "/api/agendatec/v2/admin/requests",
    "agendatec_api.api_admin.admin_requests.admin_get_request_detail":     "/api/agendatec/v2/admin/requests/{req_id}",
    "agendatec_api.api_admin.admin_requests.admin_change_request_status":  "/api/agendatec/v2/admin/requests/{req_id}/status",
    "agendatec_api.api_admin.admin_requests.admin_create_request":         "/api/agendatec/v2/admin/requests/create",
    # Admin Reports
    "agendatec_api.api_admin.admin_reports.export_requests_xlsx":  "/api/agendatec/v2/admin/reports/requests.xlsx",
    # Admin Surveys
    "agendatec_api.api_admin.admin_surveys.send_surveys":          "/api/agendatec/v2/admin/surveys/send",
    # Admin Users
    "agendatec_api.api_admin.admin_users.list_coordinators":             "/api/agendatec/v2/admin/users/coordinators",
    "agendatec_api.api_admin.admin_users.create_coordinator":            "/api/agendatec/v2/admin/users/coordinators",
    "agendatec_api.api_admin.admin_users.update_coordinator":            "/api/agendatec/v2/admin/users/coordinators/{coord_id}",
    "agendatec_api.api_admin.admin_users.list_students":                 "/api/agendatec/v2/admin/users/students",
    "agendatec_api.api_admin.admin_users.search_users_for_coordinator":  "/api/agendatec/v2/admin/users/search",

    # ── VisteTec: Páginas ────────────────────────────────────────────────────
    # Student
    "vistetec_pages.student_pages.catalog":              "/vistetec/student/catalog",
    "vistetec_pages.student_pages.garment_detail":       "/vistetec/student/catalog/{garment_id}",
    "vistetec_pages.student_pages.my_appointments":      "/vistetec/student/my-appointments",
    "vistetec_pages.student_pages.my_donations":         "/vistetec/student/my-donations",
    # Volunteer
    "vistetec_pages.volunteer_pages.dashboard":          "/vistetec/volunteer/dashboard",
    "vistetec_pages.volunteer_pages.garment_form":       "/vistetec/volunteer/garment/new",
    "vistetec_pages.volunteer_pages.garment_edit":       "/vistetec/volunteer/garment/{garment_id}/edit",
    "vistetec_pages.volunteer_pages.appointments":       "/vistetec/volunteer/appointments",
    "vistetec_pages.volunteer_pages.register_donation":  "/vistetec/volunteer/donations/register",
    # Admin
    "vistetec_pages.admin_pages.dashboard":              "/vistetec/admin/dashboard",
    "vistetec_pages.admin_pages.garments":               "/vistetec/admin/garments",
    "vistetec_pages.admin_pages.pantry":                 "/vistetec/admin/pantry",
    "vistetec_pages.admin_pages.campaigns":              "/vistetec/admin/campaigns",
    "vistetec_pages.admin_pages.reports":                "/vistetec/admin/reports",
}


# ---------------------------------------------------------------------------
# url_for compatible con Flask (para templates compartidos)
# ---------------------------------------------------------------------------


def _make_url_for() -> Callable[..., str]:
    """Crea una función url_for() compatible con los templates de Flask.

    Maneja dos casos:
    1. Archivos estáticos: ``url_for('static', filename='core/css/auth.css')``
       → ``/static/core/css/auth.css``
    2. Endpoints nombrados: ``url_for('pages_core.pages_auth.login_page')``
       → ``/itcj/login`` (vía ENDPOINT_MAP)
    """

    def url_for(endpoint: str, **kwargs: str) -> str:
        if endpoint == "static":
            filename = kwargs.get("filename", "")
            return f"/static/{filename}"

        url = ENDPOINT_MAP.get(endpoint, "#")
        # Sustituir path params: /config/users/{user_id} → /config/users/42
        for key, value in kwargs.items():
            url = url.replace(f"{{{key}}}", str(value))
        return url

    return url_for


# ---------------------------------------------------------------------------
# is_active (equivalente al context processor de Flask)
# ---------------------------------------------------------------------------


def _make_is_active(current_path: str) -> Callable[[str], bool]:
    """Crea la función is_active() para detectar la ruta activa en el navbar."""

    def is_active(url: str) -> bool:
        normalized = url.rstrip("/")
        return current_path == url or current_path.startswith(normalized + "/")

    return is_active


# ---------------------------------------------------------------------------
# nav_for (navegación global del sistema, equivalente al context processor)
# ---------------------------------------------------------------------------


def _make_nav_for(user: dict | None) -> Callable[[str | None], list[dict]]:
    """Crea la función nav_for() con la navegación global según el rol."""

    url_for = _make_url_for()

    def _icon_for(label: str) -> str:
        lbl = (label or "").lower()
        if "dashboard" in lbl:
            return "bi-grid"
        if "configuración" in lbl:
            return "bi-gear-fill"
        if "perfil" in lbl:
            return "bi-person"
        if "logout" in lbl:
            return "bi-box-arrow-right"
        return "bi-circle"

    def nav_for(role: str | None) -> list[dict]:
        """Navegación GLOBAL del sistema (no específica de apps)."""
        if not role:
            return []

        nav_items = []

        if role == "admin":
            nav_items.append({
                "label": "Configuración",
                "endpoint": "pages_core.pages_config.settings",
                "roles": ["admin"],
            })

        filtered = [item for item in nav_items if role in item["roles"]]

        return [
            {
                "label": item["label"],
                "endpoint": item["endpoint"],
                "url": url_for(item["endpoint"]),
                "icon": _icon_for(item["label"]),
            }
            for item in filtered
        ]

    return nav_for


# ---------------------------------------------------------------------------
# active_theme
# ---------------------------------------------------------------------------


def _get_active_theme() -> dict | None:
    """Obtiene el tema visual activo del sistema (equivalente al context processor de Flask)."""
    try:
        from itcj2.core.services import themes_service  # type: ignore[import]

        theme = themes_service.get_active_theme()
        if theme:
            return theme.to_dict(include_full=True)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# render() — función principal de renderizado
# ---------------------------------------------------------------------------


def render(
    request: Request,
    template: str,
    context: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Renderiza un template con el contexto global inyectado automáticamente.

    Equivale a ``render_template()`` de Flask con todos los context_processors
    ya incluidos. Inyecta:

    - ``request``             → proxy Flask-compatible de Starlette Request
    - ``current_user``        → payload JWT del usuario (o None)
    - ``sv``                  → función de versionado de estáticos
    - ``static_version``      → versión global de fallback
    - ``url_for``             → función compatible con templates Flask
    - ``is_active``           → detecta si una URL es la activa en el navbar
    - ``nav_for``             → navegación global por rol
    - ``active_theme``        → tema visual activo del sistema
    - ``get_flashed_messages``→ stub que retorna [] (flash no existe en FastAPI)
    """
    current_user = getattr(request.state, "current_user", None)

    ctx: dict[str, Any] = {
        "request": _TemplateRequest(request),
        "current_user": current_user,
        "sv": sv,
        "static_version": get_settings().STATIC_VERSION,
        "url_for": _make_url_for(),
        "is_active": _make_is_active(request.url.path),
        "nav_for": _make_nav_for(current_user),
        "active_theme": _get_active_theme(),
        # Flash messages no existen en FastAPI; retorna lista vacía para
        # que los templates que usan get_flashed_messages() no fallen.
        "get_flashed_messages": lambda *args, **kwargs: [],
    }

    if context:
        ctx.update(context)

    return templates.TemplateResponse(request, template, ctx, status_code=status_code)
