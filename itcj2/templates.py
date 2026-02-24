import os

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .config import get_settings, load_static_manifest

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

templates = Jinja2Templates(
    directory=[
        os.path.join(_BASE, "itcj", "core", "templates"),
        os.path.join(_BASE, "itcj", "apps", "agendatec", "templates"),
        os.path.join(_BASE, "itcj", "apps", "helpdesk", "templates"),
        os.path.join(_BASE, "itcj", "apps", "vistetec", "templates"),
    ]
)

_manifest: dict | None = None


def _get_manifest() -> dict:
    global _manifest
    if _manifest is None:
        _manifest = load_static_manifest()
    return _manifest


def sv(app_name: str, filename: str) -> str:
    """Retorna el hash de un archivo estático (igual que sv() de Flask)."""
    fallback = get_settings().STATIC_VERSION
    return _get_manifest().get(app_name, {}).get(filename, fallback)


def render(
    request: Request,
    template: str,
    context: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Renderiza un template con el contexto global inyectado.

    Equivale a render_template() de Flask pero con los context_processors
    incluidos automáticamente.
    """
    ctx = {
        "request": request,
        "current_user": getattr(request.state, "current_user", None),
        "sv": sv,
        "static_version": get_settings().STATIC_VERSION,
    }
    if context:
        ctx.update(context)

    return templates.TemplateResponse(template, ctx, status_code=status_code)
