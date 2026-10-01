"""Render helper + instancia Jinja2 propia de la app adhoc (espejo de directory)."""
import logging
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

_HERE = Path(__file__).parent
_TEMPLATES_DIR = _HERE.parent / "templates"

# OJO: ``directory=`` es el kwarg de Starlette, no el nombre de la app.
adhoc_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _sv_for(app_name: str, path: str) -> str:
    try:
        from itcj2.templates import sv as _sv_global
        return _sv_global(app_name, path)
    except Exception:
        try:
            from itcj2.config import get_settings
            return str(get_settings().STATIC_VERSION)
        except Exception:
            return "0"


def sv(path: str) -> str:
    """Versión de un estático de adhoc vía el manifest global → fallback STATIC_VERSION."""
    return _sv_for("adhoc", path)


def sv_core(path: str) -> str:
    """Versión de un estático de core (shell móvil compartido)."""
    return _sv_for("core", path)


def render_adhoc(request: Request, template: str, context: dict | None = None, status_code: int = 200) -> HTMLResponse:
    """Renderiza un template de adhoc con el contexto estándar inyectado."""
    user = getattr(request.state, "current_user", None)
    ctx: dict = {
        "request": request,
        "current_user": user,
        "sv": sv,
        "sv_core": sv_core,
        "current_route": request.url.path,
        **(context or {}),
    }
    return adhoc_templates.TemplateResponse(request, template, ctx, status_code=status_code)
