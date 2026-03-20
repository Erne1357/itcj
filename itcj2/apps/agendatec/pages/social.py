"""
Páginas de servicio social para AgendaTec.
Equivalente a itcj/apps/agendatec/routes/pages/social.py.

Rutas:
  GET /agendatec/social/home  → Vista de citas del día (servicio social)
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.apps.agendatec.pages.nav import render_agendatec
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.agendatec.pages.social")

router = APIRouter(prefix="/social", tags=["agendatec-pages-social"])


@router.get("/home", name="agendatec.pages.social.home")
async def social_home(
    request: Request,
    user: dict = Depends(require_page_app("agendatec", perms=["agendatec.social.page.home"])),
):
    """Vista de citas del día para servicio social."""
    return render_agendatec(request, "agendatec/social/home.html", {
        "title": "Servicio Social - Citas del día",
    })
