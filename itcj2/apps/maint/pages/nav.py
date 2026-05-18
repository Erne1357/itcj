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


def _build_maint_nav(user_id: int, current_path: str, db, jwt_role: str | None = None) -> dict:
    """Construye items de navegación filtrados por rol y permisos del usuario.

    `jwt_role` es el `role` del JWT: si es "admin" se trata como admin
    global (bypassa permisos granulares, igual que require_perms).
    """
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

    # ── Administración (dropdown filtrado por permisos granulares) ──────────
    # Cada item aparece si el usuario tiene el permiso correspondiente.
    # Admin global (rol "admin" en maint) bypassa los chequeos.
    is_admin_role = "admin" in roles
    admin_dropdown = []

    def _adm(label, icon, url, perm):
        if is_admin_role or perm in perms:
            admin_dropdown.append({"label": label, "icon": icon, "url": url})

    # Dashboard departamental aparece si tiene full O summary
    if is_admin_role or "maint.dashboard.page.full" in perms or "maint.dashboard.page.summary" in perms:
        admin_dropdown.append({
            "label": "Dashboard depto",
            "icon": "fa-gauge-high",
            "url": "/maint/admin/dashboard",
        })
    _adm("Categorías",     "fa-tags",       "/maint/admin/categories", "maint.admin.page.categories")
    _adm("Áreas Técnicas", "fa-users-cog",  "/maint/admin/areas",      "maint.admin.page.areas")
    _adm("Reportes",       "fa-chart-bar",  "/maint/admin/reports",    "maint.admin.page.reports")
    _adm("Estadísticas",   "fa-chart-pie",  "/maint/admin/stats",      "maint.stats.page.list")
    _adm("Análisis",       "fa-microscope", "/maint/admin/analysis",   "maint.analysis.page.list")

    if admin_dropdown:
        items.append({
            "label": "Administración",
            "icon": "fa-cog",
            "dropdown": admin_dropdown,
        })

    # ── Almacén (dropdown filtrado por perms granulares warehouse) ───────────
    # Perms warehouse se derivan del rol maint del usuario vía
    # core_role_permissions (cross-app). Admin global del JWT bypassa.
    try:
        from itcj2.apps.maint.utils.warehouse_auth import get_warehouse_perms_via_maint
        wh_perms = get_warehouse_perms_via_maint(db, user_id)
    except Exception as exc:
        logger.warning("Error obteniendo warehouse perms para user %s: %s", user_id, exc)
        wh_perms = set()

    warehouse_items = []

    def _wh(label, icon, url, perm):
        if is_admin_role or perm in wh_perms:
            warehouse_items.append({"label": label, "icon": icon, "url": url})

    _wh("Dashboard",         "fa-tachometer-alt", "/maint/warehouse/dashboard",  "warehouse.page.dashboard")
    _wh("Productos",         "fa-cube",           "/maint/warehouse/products",   "warehouse.page.products")
    _wh("Categorías",        "fa-folder-open",    "/maint/warehouse/categories", "warehouse.page.categories")
    _wh("Entradas de Stock", "fa-truck-loading",  "/maint/warehouse/entries",    "warehouse.page.entries")
    _wh("Movimientos",       "fa-exchange-alt",   "/maint/warehouse/movements",  "warehouse.page.movements")

    if warehouse_items:
        items.append({
            "label": "Almacén",
            "icon": "fa-boxes",
            "dropdown": warehouse_items,
        })

    # ── Ayuda (visible solo si tiene al menos un perm de help) ───────────────
    # Granular 100% por permiso. Admin (rol maint "admin" o admin global del
    # JWT) bypassa perms — ve las 3 pestañas y todas las guías.
    is_admin_global = ("admin" in roles) or (str(jwt_role) == "admin")
    has_requester = is_admin_global or "maint.help.page.requester" in perms
    has_admin_help = is_admin_global or "maint.help.page.admin" in perms
    has_tech_help = is_admin_global or "maint.help.page.tech" in perms

    if has_requester or has_admin_help or has_tech_help:
        # URL preferida = la primera que el usuario tenga acceso, en este orden:
        # requester > admin > tech. Un tech_maint sin perm requester aterriza
        # directo en /maint/help/tech.
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

    # ── Cómputo de "active" con best-match (URL más larga gana) ──────────────
    # Evita que /maint/tickets/create marque también el item "Tickets".
    _mark_active_items(items, current_path)

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
        # Si True, las guías de /maint/help/* se muestran todas sin gating.
        "help_all": is_admin_global,
    }


def _mark_active_items(items: list[dict], current_path: str) -> None:
    """Marca a lo sumo un item/sub como `active` usando best-match.

    Regla: gana la URL más larga que sea igual a `current_path` o prefijo
    estricto (`current_path == url` o `current_path.startswith(url + '/')`).
    Así `/maint/tickets/create` activa "Nueva Solicitud" y no "Tickets",
    pero `/maint/tickets/123` (detalle) sí activa "Tickets".

    Mutación: agrega `active=True` al item/sub ganador y `group_active=True`
    al dropdown que lo contiene.
    """
    # Recolecta candidatos (url, target_dict, parent_dict_or_None)
    candidates: list[tuple[str, dict, dict | None]] = []
    for it in items:
        if it.get("dropdown"):
            for sub in it["dropdown"]:
                url = sub.get("url")
                if url:
                    candidates.append((url, sub, it))
        else:
            url = it.get("url")
            if url:
                candidates.append((url, it, None))

    def _matches(url: str) -> bool:
        return current_path == url or current_path.startswith(url.rstrip("/") + "/")

    matching = [c for c in candidates if _matches(c[0])]
    if not matching:
        return
    # Gana la URL más larga (más específica)
    _, target, parent = max(matching, key=lambda c: len(c[0]))
    target["active"] = True
    if parent is not None:
        parent["group_active"] = True


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
                nav_ctx = _build_maint_nav(
                    int(user["sub"]),
                    request.url.path,
                    _db,
                    jwt_role=user.get("role"),
                )
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
