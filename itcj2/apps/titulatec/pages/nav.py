"""Templates nativo + helpers de navegación para TitulaTec.

Usa su propia instancia de Jinja2Templates (independiente de itcj2/templates.py),
genera URLs directas y versiona estáticos vía el sv() global (nginx sirve /static/titulatec).
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Request
from starlette.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger("itcj2.apps.titulatec.pages")

_HERE = Path(__file__).parent
_TEMPLATES_DIR = _HERE.parent / "templates"

# Instancia propia de Jinja2Templates — no toca itcj2/templates.py
titulatec_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def sv(path: str) -> str:
    """Versión de un estático de titulatec vía el manifest global → fallback STATIC_VERSION."""
    try:
        from itcj2.templates import sv as _sv_global
        return _sv_global("titulatec", path)
    except Exception:
        try:
            from itcj2.config import get_settings
            return str(get_settings().STATIC_VERSION)
        except Exception:
            return "0"


def sv_core(path: str) -> str:
    """Versión de un estático del CORE (p. ej. el shell mobile reutilizado por el alumno)."""
    try:
        from itcj2.templates import sv as _sv_global
        return _sv_global("core", path)
    except Exception:
        try:
            from itcj2.config import get_settings
            return str(get_settings().STATIC_VERSION)
        except Exception:
            return "0"


# ---------------------------------------------------------------------------
# Resolución del dashboard por rol (landing)
# ---------------------------------------------------------------------------

# Orden de prioridad: el primero que matchee gana.
_ROLE_DASHBOARD = [
    ("admin",                     "/titulatec/admin/"),
    ("titulatec_titulaciones",    "/titulatec/admin/"),
    ("titulatec_school_services", "/titulatec/admin/"),
    ("titulatec_vinculacion",     "/titulatec/vinculacion/"),
    ("titulatec_sinodal",         "/titulatec/sinodal/"),
    ("student",                   "/titulatec/student/dashboard"),  # rol global reciclado
]


def resolve_dashboard_url(roles: set[str], jwt_role: str | None = None) -> str:
    """Devuelve la URL de dashboard según los roles del usuario en la app."""
    if jwt_role == "admin":
        return "/titulatec/admin/"
    for role_name, url in _ROLE_DASHBOARD:
        if role_name in roles:
            return url
    # Sin rol de la app → de vuelta al dashboard core
    return "/itcj/dashboard"


def get_titulatec_roles(user_id: int) -> set[str]:
    """Roles del usuario en la app titulatec (directos + por puesto)."""
    from itcj2.database import SessionLocal
    from itcj2.core.services.authz_service import user_roles_in_app
    db = SessionLocal()
    try:
        return set(user_roles_in_app(db, user_id, "titulatec"))
    except Exception as exc:
        logger.warning("Error obteniendo roles titulatec para user %s: %s", user_id, exc)
        return set()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render_titulatec(
    request: Request,
    template: str,
    context: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Renderiza un template de TitulaTec con el contexto estándar inyectado."""
    user = getattr(request.state, "current_user", None)
    ctx: dict = {
        "request": request,
        "current_user": user,
        "sv": sv,
        "sv_core": sv_core,
        "current_route": request.url.path,
        **(context or {}),
    }
    return titulatec_templates.TemplateResponse(request, template, ctx, status_code=status_code)
