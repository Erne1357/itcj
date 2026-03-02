"""
Landing page de VisteTec.
Equivalente a la ruta ``@vistetec_pages_bp.get("/")`` de Flask.

Rutas:
  GET /vistetec/  → Landing page
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.apps.vistetec.pages.nav import render_vistetec
from itcj2.dependencies import require_page_login

logger = logging.getLogger("itcj2.apps.vistetec.pages.landing")

router = APIRouter(tags=["vistetec-pages-landing"])


@router.get("/", name="vistetec.pages.landing.home")
async def home(
    request: Request,
    user: dict = Depends(require_page_login),
):
    """Landing page de VisteTec."""
    return render_vistetec(request, "vistetec/home.html", {"title": "VisteTec"})
