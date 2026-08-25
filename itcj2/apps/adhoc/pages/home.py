"""Raíz de Adhoc (Calidad): redirección al dashboard + placeholder de migración."""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from itcj2.database import get_db
from itcj2.dependencies import require_page_login
from itcj2.apps.adhoc.pages.nav import nav_for_user
from itcj2.apps.adhoc.pages.render import render_adhoc

logger = logging.getLogger(__name__)

router = APIRouter()

_DASHBOARD_URL = "/adhoc/dashboard"


# ── Raíz: /adhoc y /adhoc/ → /adhoc/dashboard ────────────────────────────────
async def root_no_slash() -> RedirectResponse:
    """GET /adhoc (sin barra final).

    Se monta a mano desde ``pages/router.py`` con ``add_api_route("")`` en lugar
    de decorarse aquí: FastAPI rechaza ``include_router()`` de un sub-router que
    tenga una ruta con path vacío cuando el prefijo de inclusión también lo está
    ("Prefix and path cannot be both empty"). Sobre el router padre, su
    ``prefix="/adhoc"`` ya aporta la ruta completa.
    """
    return RedirectResponse(_DASHBOARD_URL, status_code=302)


@router.get("/")
async def root() -> RedirectResponse:
    """GET /adhoc/ (con barra final)."""
    return RedirectResponse(_DASHBOARD_URL, status_code=302)


# TODO(F5): esta vista es TEMPORAL. El dashboard real ("Tareas") se implementa en
# F5 con `Depends(require_page_app("adhoc", perms=["adhoc.dashboard.page.view"]))`
# y su propio template. Aquí solo se usa require_page_login porque en F0 ni la
# fila de core_apps ni los permisos adhoc.* existen todavía: cualquier gate por
# app o por permiso daría 403 a todo el mundo.
@router.get("/dashboard")
async def dashboard_placeholder(
    request: Request,
    user: dict = Depends(require_page_login),
    db: Session = Depends(get_db),
):
    return render_adhoc(
        request,
        "adhoc/home_placeholder.html",
        {"nav": nav_for_user(db, user)},
    )
