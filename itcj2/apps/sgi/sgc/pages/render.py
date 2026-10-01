"""Render helper + instancia Jinja2 propia de la app sgc (espejo de directory)."""
import logging
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

_HERE = Path(__file__).parent
_TEMPLATES_DIR = _HERE.parent / "templates"

# OJO: ``directory=`` es el kwarg de Starlette, no el nombre de la app.
sgc_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


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
    """Versión de un estático del módulo SGC vía el manifest global → fallback STATIC_VERSION.

    La llave del manifest es `sgi` y su raíz es `itcj2/apps/sgi/sgc/static`, servida en
    `/static/sgi/sgc/`: los estáticos viven DENTRO del módulo. Cuando entren `buzon` y
    `encuestas`, cada uno trae su propia llave y su propio bloque de nginx — tres líneas
    por módulo, a cambio de que los tests sigan resolviendo rutas desde la raíz del módulo.
    """
    return _sv_for("sgi", path)


def sv_core(path: str) -> str:
    """Versión de un estático de core (shell móvil compartido)."""
    return _sv_for("core", path)


def render_sgc(request: Request, template: str, context: dict | None = None, status_code: int = 200) -> HTMLResponse:
    """Renderiza un template de sgc con el contexto estándar inyectado."""
    user = getattr(request.state, "current_user", None)
    ctx: dict = {
        "request": request,
        "current_user": user,
        "sv": sv,
        "sv_core": sv_core,
        "current_route": request.url.path,
        **(context or {}),
    }
    return sgc_templates.TemplateResponse(request, template, ctx, status_code=status_code)
