"""Raíz de Adhoc (Calidad): ``/adhoc`` y ``/adhoc/`` → ``/adhoc/dashboard``.

El dashboard real ("Tareas") vive en `pages/dashboard.py`; aquí solo queda la
redirección de la raíz, que es la URL registrada en ``core_apps.mobile_url``.

Gate: plan §4 pide **login** para la raíz. Se usa ``require_page_login`` y no
``require_page_app`` a propósito — el gate de app/permiso lo pone el destino
(`/adhoc/dashboard`, con ``adhoc.dashboard.page.view``), y duplicarlo aquí solo
cambiaría el 302-a-login por un 403 renderizado antes de que el usuario llegue a
ver la app. Sí hace falta el login: sin él un anónimo recibiría un 302 a
`/adhoc/dashboard` en vez de al login.
"""
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from itcj2.dependencies import require_page_login

logger = logging.getLogger(__name__)

router = APIRouter()

_DASHBOARD_URL = "/adhoc/dashboard"


async def root_no_slash(user: dict = Depends(require_page_login)) -> RedirectResponse:
    """GET /adhoc (sin barra final).

    Se monta a mano desde ``pages/router.py`` con ``add_api_route("")`` en lugar
    de decorarse aquí: FastAPI rechaza ``include_router()`` de un sub-router que
    tenga una ruta con path vacío cuando el prefijo de inclusión también lo está
    ("Prefix and path cannot be both empty"). Sobre el router padre, su
    ``prefix="/adhoc"`` ya aporta la ruta completa.
    """
    return RedirectResponse(_DASHBOARD_URL, status_code=302)


@router.get("/")
async def root(user: dict = Depends(require_page_login)) -> RedirectResponse:
    """GET /adhoc/ (con barra final)."""
    return RedirectResponse(_DASHBOARD_URL, status_code=302)
