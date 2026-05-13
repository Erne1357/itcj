"""
Templates nativo + navegación para la app de Mantenimiento.

Usa su propia instancia de Jinja2Templates (independiente de itcj2/templates.py)
y genera URLs directas (no usa ENDPOINT_MAP ni url_for de Flask).
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse

logger = logging.getLogger("itcj2.apps.maint.pages")

# ---------------------------------------------------------------------------
# Directorios
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
_TEMPLATES_DIR = _HERE.parent / "templates"
_STATIC_DIR = _HERE.parent / "static"

# Instancia propia de Jinja2Templates — no toca itcj2/templates.py
maint_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# ---------------------------------------------------------------------------
# Versioning de archivos estáticos (MD5 del contenido, cacheado)
# ---------------------------------------------------------------------------

_hash_cache: dict[str, str] = {}


def sv(path: str) -> str:
    """Hash MD5 (8 chars) del archivo estático de maint para cache-busting.

    Uso en templates: /static/maint/css/maint.css?v={{ sv('css/maint.css') }}
    """
    if path not in _hash_cache:
        full = _STATIC_DIR / path
        if full.exists():
            _hash_cache[path] = hashlib.md5(full.read_bytes()).hexdigest()[:8]
        else:
            _hash_cache[path] = "dev"
    return _hash_cache[path]


def sv_core(path: str) -> str:
    """Hash para archivos estáticos de core (usa el sistema de manifest global)."""
    try:
        from itcj2.templates import sv as _sv_global
        return _sv_global("core", path)
    except Exception:
        return "0"


# ---------------------------------------------------------------------------
# Construcción de navegación por rol
# ---------------------------------------------------------------------------

_FULL_ACCESS = {"admin", "dispatcher", "tech_maint"}
_DEPT_ACCESS = {"department_head", "secretary"}
_CREATOR_ROLES = {"admin", "dispatcher", "department_head", "secretary", "staff"}


def _build_maint_nav(user_id: int, current_path: str, db) -> dict:
    """Construye items de navegación filtrados por rol y permisos del usuario."""
    from itcj2.core.services.authz_service import (
        user_roles_in_app,
        user_direct_perms_in_app,
        perms_via_roles,
    )

    try:
        roles = set(user_roles_in_app(db, user_id, "maint"))
    except Exception as exc:
        logger.warning("Error obteniendo roles maint para user %s: %s", user_id, exc)
        roles = set()

    try:
        perms = set(user_direct_perms_in_app(db, user_id, "maint")) | set(perms_via_roles(db, user_id, "maint"))
    except Exception as exc:
        logger.warning("Error obteniendo perms maint para user %s: %s", user_id, exc)
        perms = set()

    items = []

    # ── Tickets ──────────────────────────────────────────────────────────────
    # Todos los roles con acceso a maint ven la lista (scope aplicado en backend)
    items.append({
        "label": "Tickets",
        "icon": "fa-clipboard-list",
        "url": "/maint/tickets",
    })

    # ── Nueva Solicitud ───────────────────────────────────────────────────────
    if roles & _CREATOR_ROLES:
        items.append({
            "label": "Nueva Solicitud",
            "icon": "fa-plus-circle",
            "url": "/maint/tickets/create",
        })

    # ── Administración (dropdown) ─────────────────────────────────────────────
    if roles & {"admin", "dispatcher"}:
        dropdown = []
        if "admin" in roles:
            dropdown.append({
                "label": "Categorías",
                "icon": "fa-tags",
                "url": "/maint/admin/categories",
            })
            dropdown.append({
                "label": "Áreas Técnicas",
                "icon": "fa-users-cog",
                "url": "/maint/admin/areas",
            })
        dropdown.append({
            "label": "Reportes",
            "icon": "fa-chart-bar",
            "url": "/maint/admin/reports",
        })
        dropdown.append({
            "label": "Estadísticas",
            "icon": "fa-chart-pie",
            "url": "/maint/admin/stats",
        })
        dropdown.append({
            "label": "Análisis",
            "icon": "fa-microscope",
            "url": "/maint/admin/analysis",
        })
        items.append({
            "label": "Administración",
            "icon": "fa-cog",
            "dropdown": dropdown,
        })

    # ── Almacén (dropdown filtrado por perms granulares) ─────────────────────
    # Cada item aparece si el usuario tiene su perm específico.
    # Admin global del JWT (rol "admin" en maint) bypassa perms.
    is_admin_role = "admin" in roles
    warehouse_items = []

    def _wh(label, icon, url, perm):
        if is_admin_role or perm in perms:
            warehouse_items.append({"label": label, "icon": icon, "url": url})

    _wh("Dashboard",         "fa-tachometer-alt", "/maint/warehouse/dashboard",  "maint.warehouse.page.dashboard")
    _wh("Productos",         "fa-cube",           "/maint/warehouse/products",   "maint.warehouse.page.products")
    _wh("Categorías",        "fa-folder-open",    "/maint/warehouse/categories", "maint.warehouse.page.categories")
    _wh("Entradas de Stock", "fa-truck-loading",  "/maint/warehouse/entries",    "maint.warehouse.page.entries")
    _wh("Movimientos",       "fa-exchange-alt",   "/maint/warehouse/movements",  "maint.warehouse.page.movements")

    if warehouse_items:
        items.append({
            "label": "Almacén",
            "icon": "fa-boxes",
            "dropdown": warehouse_items,
        })

    # ── Ayuda (visible solo si tiene al menos un perm de help) ───────────────
    is_admin_global = "admin" in roles  # admin global bypassa perms granulares
    has_requester = is_admin_global or "maint.help.page.requester" in perms
    has_admin_help = is_admin_global or "maint.help.page.admin" in perms
    has_tech_help = is_admin_global or "maint.help.page.tech" in perms

    if has_requester or has_admin_help or has_tech_help:
        # URL preferida = la primera que el usuario tenga acceso, en este orden:
        # requester > admin > tech (cubre la mayoría de los roles)
        if has_requester:
            help_url = "/maint/help"
        elif has_admin_help:
            help_url = "/maint/help/admin"
        else:
            help_url = "/maint/help/tech"

        items.append({
            "label": "Ayuda",
            "icon": "fa-circle-question",
            "url": help_url,
        })

    return {
        "maint_nav_items": items,
        "current_route": current_path,
        "user_roles": list(roles),
        "user_perms": list(perms),
        "help_perms": {
            "requester": has_requester,
            "admin": has_admin_help,
            "tech": has_tech_help,
        },
    }


# ---------------------------------------------------------------------------
# Helper de renderizado
# ---------------------------------------------------------------------------

def render_maint(
    request: Request,
    template: str,
    context: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Renderiza un template de Mantenimiento con el contexto estándar inyectado.

    Equivalente a render_helpdesk() pero para maint, usando su propia instancia
    de Jinja2Templates sin pasar por itcj2/templates.py.
    """
    user = getattr(request.state, "current_user", None)

    nav_ctx: dict = {"maint_nav_items": [], "current_route": request.url.path}

    if user:
        try:
            from itcj2.database import SessionLocal
            _db = SessionLocal()
            try:
                nav_ctx = _build_maint_nav(int(user["sub"]), request.url.path, _db)
            finally:
                _db.close()
        except Exception as exc:
            logger.warning("Error construyendo nav maint: %s", exc)

    ctx: dict = {
        "request": request,
        "current_user": user,
        "sv": sv,           # versioning de /static/maint/...
        "sv_core": sv_core, # versioning de /static/core/...
        **(context or {}),
        **nav_ctx,
    }

    return maint_templates.TemplateResponse(
        request,
        template,
        ctx,
        status_code=status_code,
    )
