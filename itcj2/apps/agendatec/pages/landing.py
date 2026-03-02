"""
Landing page de AgendaTec — redirige al home según el rol del usuario.
Equivalente a la ruta ``@agendatec_pages_bp.get("/")`` de Flask.

Rutas:
  GET /agendatec/  → Redirige al dashboard según rol
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from itcj2.dependencies import require_page_login

logger = logging.getLogger("itcj2.apps.agendatec.pages.landing")

router = APIRouter(tags=["agendatec-pages-landing"])

_ROLE_HOME: dict[str, str] = {
    "student":      "/agendatec/student/home",
    "coordinator":  "/agendatec/coord/home",
    "social_service": "/agendatec/social/home",
    "admin":        "/agendatec/admin/home",
}


@router.get("/", name="agendatec.pages.landing.home")
async def home(
    request: Request,
    user: dict = Depends(require_page_login),
):
    """Redirige al dashboard de AgendaTec según el rol del usuario."""
    from itcj2.apps.agendatec.utils.utils import get_role_agenda

    user_id = int(user["sub"])
    role = get_role_agenda(user_id)
    destination = _ROLE_HOME.get(role or "", "/agendatec/student/home")
    logger.debug("Redirigiendo usuario %s (rol=%s) a %s", user_id, role, destination)
    return RedirectResponse(destination, status_code=302)
