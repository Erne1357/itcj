"""Render helper + instancia Jinja2 propia de la app directory (espejo de titulatec)."""
import logging
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

_HERE = Path(__file__).parent
_TEMPLATES_DIR = _HERE.parent / "templates"

directory_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def sv(path: str) -> str:
    """Versión de un estático de directory vía el manifest global → fallback STATIC_VERSION."""
    try:
        from itcj2.templates import sv as _sv_global
        return _sv_global("directory", path)
    except Exception:
        try:
            from itcj2.config import get_settings
            return str(get_settings().STATIC_VERSION)
        except Exception:
            return "0"


def render_directory(request: Request, template: str, context: dict | None = None, status_code: int = 200) -> HTMLResponse:
    """Renderiza un template de directory con el contexto estándar inyectado."""
    user = getattr(request.state, "current_user", None)
    ctx: dict = {
        "request": request,
        "current_user": user,
        "sv": sv,
        "current_route": request.url.path,
        **(context or {}),
    }
    return directory_templates.TemplateResponse(request, template, ctx, status_code=status_code)
