"""Landing de TitulaTec — redirige al dashboard según el rol del usuario."""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import get_titulatec_roles, resolve_dashboard_url

logger = logging.getLogger("itcj2.apps.titulatec.pages.landing")

router = APIRouter(tags=["titulatec-pages-landing"])


@router.get("/", name="titulatec.pages.landing")
async def landing(
    request: Request,
    user: dict = Depends(require_page_app("titulatec")),
):
    """Redirige al dashboard correspondiente al rol del usuario en la app."""
    roles = get_titulatec_roles(int(user["sub"]))
    url = resolve_dashboard_url(roles, jwt_role=user.get("role"))
    return RedirectResponse(url, status_code=302)
