"""
Landing page de AgendaTec — redirige al home según el rol del usuario.
Equivalente a la ruta ``@agendatec_pages_bp.get("/")`` de Flask.

Rutas:
  GET /prorrogas_tec/  → Redirige al dashboard según rol
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from itcj2.dependencies import require_page_login

logger = logging.getLogger("itcj2.apps.prorrogas_tec.pages.landing")

router = APIRouter(tags=["prorrogas_tec-pages-landing"])

_ROLE_HOME: dict[str, str] = {
    "student":      "/prorrogas/student/home",
    # "coordinator":  "/prorrogas_tec/coord/home",
    # "social_service": "/prorrogas_tec/social/home",
    "admin":        "/prorrogas/admin/home",
}


@router.get("/", name="prorrogas_tec.pages.landing.home")
async def home(
    request: Request,
    user: dict = Depends(require_page_login),
):
    """Redirige al dashboard de AgendaTec según el rol del usuario."""
    from itcj2.apps.prorrogas_tec.utils.utils import get_role_prorroga

    user_id = int(user["sub"])
    role = get_role_prorroga(user_id)
    destination = _ROLE_HOME.get(role or "", "/prorrogas/student/home")
    logger.debug("Redirigiendo usuario %s (rol=%s) a %s", user_id, role, destination)
    return RedirectResponse(destination, status_code=302)
