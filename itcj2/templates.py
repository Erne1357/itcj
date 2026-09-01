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
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import json

from .config import get_settings, load_static_manifest
from itcj2.core.utils.redis_conn import get_redis

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
        # Prórrogas usa `render()` de este módulo (no una instancia propia de
        # Jinja2Templates como titulatec/directory), así que sus templates
        # tienen que estar en ESTE searchpath o `render` no los encuentra.
        os.path.join(_BASE, "itcj2", "apps", "prorrogas_tec", "templates"),
    ]
)


# ---------------------------------------------------------------------------
# Filtros Jinja compartidos para componentes server-side (prefijo hd_*).
# Usados por los macros de helpdesk/_components/ (ticket_card, etc.).
# ---------------------------------------------------------------------------
from datetime import datetime as _dt  # noqa: E402


def _hd_parse_dt(value):
    if value is None or value == "":
        return None
    if isinstance(value, _dt):
        return value
    try:
        return _dt.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def hd_datetime(value, fmt: str = "%d/%m/%Y %H:%M") -> str:
    d = _hd_parse_dt(value)
    return d.strftime(fmt) if d else ""


def hd_date(value, fmt: str = "%d/%m/%Y") -> str:
    d = _hd_parse_dt(value)
    return d.strftime(fmt) if d else ""


import markupsafe  # noqa: E402

_HD_BOOST_ATTR = markupsafe.Markup('hx-boost="true"')
_HD_BOOST_EMPTY = markupsafe.Markup("")


def hd_boost(url) -> markupsafe.Markup:
    """Devuelve ``hx-boost="true"`` si ``url`` apunta a una página de Help-Desk
    migrada (morph-navegable), o cadena vacía si no.

    Uso en templates: ``<a href="{{ url }}" {{ hd_boost(url) }}>`` (los enlaces de
    CONTENIDO helpdesk→helpdesk navegan con morph, igual que la navbar). Reusa la
    MISMA lógica que decide el boost del nav (``is_boostable_url`` en
    ``pages/nav.py``); import perezoso para evitar el import circular (nav.py
    importa de este módulo), igual que ``hd_datetime`` se registra aquí.
    """
    try:
        from itcj2.apps.helpdesk.pages.nav import is_boostable_url

        if is_boostable_url(url):
            return _HD_BOOST_ATTR
    except Exception:  # pragma: no cover - defensivo: nunca romper el render
        logger.debug("hd_boost no pudo resolver %r", url, exc_info=True)
    return _HD_BOOST_EMPTY


def hd_origin(request, default_slug: str) -> dict:
    """Resuelve el destino del botón "Volver" en el SERVIDOR.

    El helper de cliente (``HelpdeskUtils.initBackButton``) sigue refinando el
    destino cuando no hay ``?from=`` —usa el origen que dejó la navegación morph
    en sessionStorage— pero el href tiene que existir ya en el HTML: los módulos
    de página se cargan por ``<script>`` inyectado, así que entre el settle del
    morph y el init del módulo el botón quedaba en ``href="#"`` y un click ahí no
    navegaba a ningún lado.

    Devuelve siempre un dict con ``url``/``label``/``icon``.
    """
    from itcj2.apps.helpdesk.pages.origins import resolve_origin

    slug = None
    try:
        slug = request.query_params.get("from")
    except Exception:  # pragma: no cover - defensivo: nunca romper el render
        logger.debug("hd_origin no pudo leer query_params", exc_info=True)
    return resolve_origin(slug) or resolve_origin(default_slug) or {
        "url": "/help-desk/",
        "label": "Volver",
        "icon": "fa-arrow-left",
    }


templates.env.filters["hd_datetime"] = hd_datetime
templates.env.filters["hd_date"] = hd_date
# Registrado como global (uso `{{ hd_boost(url) }}`) y como filtro (`{{ url | hd_boost }}`).
templates.env.globals["hd_boost"] = hd_boost
templates.env.filters["hd_boost"] = hd_boost
templates.env.globals["hd_origin"] = hd_origin

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

    # ── Help-Desk: Landing ──────────────────────────────────────────────────
    "helpdesk_pages.home":                               "/help-desk/",

    # ── Help-Desk: Páginas de usuario ───────────────────────────────────────
    "helpdesk_pages.user_pages.create_ticket":           "/help-desk/user/create",
    "helpdesk_pages.user_pages.my_tickets":              "/help-desk/user/my-tickets",
    "helpdesk_pages.inventory_pages.my_equipment":       "/help-desk/inventory/my-equipment",

    # ── Help-Desk: Dashboards por rol ────────────────────────────────────────
    "helpdesk_pages.secretary_pages.dashboard":          "/help-desk/secretary/",
    "helpdesk_pages.technician_pages.dashboard":         "/help-desk/technician/dashboard",
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
    "helpdesk_pages.admin_pages.config":                 "/help-desk/admin/config",
    "helpdesk_pages.admin_pages.inventory_categories":   "/help-desk/admin/inventory/categories",
    "helpdesk_pages.admin_pages.inventory_reports":      "/help-desk/admin/inventory/reports",

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
    # Help (mini-manual por rol)
    "agendatec_pages.help_pages.help_student":           "/agendatec/help",
    "agendatec_pages.help_pages.help_coord":             "/agendatec/help/coord",
    "agendatec_pages.help_pages.help_social":            "/agendatec/help/social",
    "agendatec_pages.help_pages.help_admin":             "/agendatec/help/admin",

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

    # ── Prórrogas: Páginas ───────────────────────────────────────────────────
    # OJO al desfase: la app se llama `prorrogas_tec` (key de core_apps, paquete
    # Python) pero sus URLs son `/prorrogas` y `/api/prorrogas/v2`, igual que
    # helpdesk vs help-desk (gotcha #12 de CLAUDE.md).
    "prorrogas_tec_pages.admin_pages.admin_home":        "/prorrogas/admin/home",
    "prorrogas_tec_pages.admin_pages.admin_requests":    "/prorrogas/admin/requests",
    "prorrogas_tec_pages.admin_pages.admin_periods":     "/prorrogas/admin/periods",

    "prorrogas_tec_pages.student_pages.student_home":        "/prorrogas/student/home",
    "prorrogas_tec_pages.student_pages.student_requests":    "/prorrogas/student/requests",
    "prorrogas_tec_pages.student_pages.student_new_request": "/prorrogas/student/request",
    "prorrogas_tec_pages.student_pages.student_close":       "/prorrogas/student/close",

    # ── Prórrogas: API ───────────────────────────────────────────────────────
    "prorrogas_tec_api.api_periods.list_periods2":         "/api/prorrogas/v2/periods",
    "prorrogas_tec_api.api_periods.create_period2":        "/api/prorrogas/v2/periods",
    "prorrogas_tec_api.api_periods.list_academic_periods": "/api/prorrogas/v2/periods/academic-periods",
    "prorrogas_tec_api.api_periods.get_period":            "/api/prorrogas/v2/periods/{period_id}",
    "prorrogas_tec_api.api_periods.update_period2":        "/api/prorrogas/v2/periods/{period_id}",
    "prorrogas_tec_api.api_periods.delete_period2":        "/api/prorrogas/v2/periods/{period_id}",

    "prorrogas_tec_api.api_admin.list_requests_admin":   "/api/prorrogas/v2/request",
    "prorrogas_tec_api.api_admin.update_request":        "/api/prorrogas/v2/request/{request_id}",
    "prorrogas_tec_api.api_admin.get_request_payments":  "/api/prorrogas/v2/request/{request_id}/payments",
    "prorrogas_tec_api.api_admin.update_payment":        "/api/prorrogas/v2/request/payments/{payment_id}",

    "prorrogas_tec_api.api_programs.list_programs":      "/api/prorrogas/v2/programs",

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

    Los kwargs que NO corresponden a un path param de la URL se anexan como
    query string, igual que Flask: ``url_for('...users_management', page=2)``
    → ``/itcj/config/users?page=2``. Antes se descartaban en silencio, lo que
    dejaba links idénticos entre sí (paginación de usuarios muerta, el
    "Conectar" de correo llegando a /email/auth/login sin ``?app=``).
    """

    def url_for(endpoint: str, **kwargs: Any) -> str:
        if endpoint == "static":
            filename = kwargs.get("filename", "")
            return f"/static/{filename}"

        url = ENDPOINT_MAP.get(endpoint, "#")
        query: dict[str, str] = {}
        # Sustituir path params: /config/users/{user_id} → /config/users/42
        for key, value in kwargs.items():
            placeholder = f"{{{key}}}"
            if placeholder in url:
                url = url.replace(placeholder, str(value))
            elif value is not None and value != "":
                query[key] = str(value)
        if query:
            url = f"{url}?{urlencode(query)}"
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


_ACTIVE_THEME_CACHE_KEY = "core:active_theme"
_ACTIVE_THEME_TTL = 300  # 5 min


def _get_active_theme() -> dict | None:
    """Tema visual activo, cacheado en Redis para no pegar a la BD en cada render."""
    # 1) Intentar cache
    r = None
    try:
        r = get_redis()
        cached = r.get(_ACTIVE_THEME_CACHE_KEY)
        if cached is not None:
            return json.loads(cached) if cached else None
    except Exception:
        r = None

    # 2) Calcular desde la BD con sesión propia
    data: dict | None = None
    try:
        from itcj2.database import SessionLocal
        from itcj2.core.services import themes_service
        with SessionLocal() as db:
            theme = themes_service.get_active_theme(db)
            if theme:
                data = theme.to_dict(include_full=True)
    except Exception:
        data = None

    # 3) Guardar en cache (incluye el "no hay tema" como "" para no recalcular)
    try:
        if r is not None:
            r.setex(_ACTIVE_THEME_CACHE_KEY, _ACTIVE_THEME_TTL, json.dumps(data) if data else "")
    except Exception:
        pass

    return data


# ---------------------------------------------------------------------------
# render() — función principal de renderizado
# ---------------------------------------------------------------------------


def initials(name: str | None) -> str:
    """Iniciales de 2 letras para avatares (coherencia móvil/desktop).

    ``full_name`` del sistema viene "APELLIDOS ... NOMBRE(S)", así que
    ``ultima_palabra + primera_palabra`` = nombre + apellido paterno → mismo
    resultado que ``first_name[:1] + last_name[:1]`` del dashboard. Un solo
    token → primeras 2 letras. Sin nombre → 'U'.
    """
    parts = (name or "").split()
    if not parts:
        return "U"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[-1][:1] + parts[0][:1]).upper()


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
        "initials": initials,
        "nav_for": _make_nav_for(current_user),
        "active_theme": _get_active_theme(),
        # Flash messages no existen en FastAPI; retorna lista vacía para
        # que los templates que usan get_flashed_messages() no fallen.
        "get_flashed_messages": lambda *args, **kwargs: [],
    }

    if context:
        ctx.update(context)

    return templates.TemplateResponse(request, template, ctx, status_code=status_code)
