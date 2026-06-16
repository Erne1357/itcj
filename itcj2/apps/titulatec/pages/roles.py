"""Páginas placeholder de sinodal y vinculación (shell Fase 0)."""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.roles")

router = APIRouter(tags=["titulatec-pages-roles"])


def _first_name(user_id: int):
    from itcj2.database import SessionLocal
    from itcj2.core.models.user import User
    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        return u.first_name if u else None
    finally:
        db.close()


@router.get("/sinodal/", name="titulatec.pages.sinodal.home")
async def sinodal_home(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.dashboard.sinodal"])),
):
    return render_titulatec(request, "titulatec/role_home.html", {
        "role_label": "Sinodal",
        "first_name": _first_name(int(user["sub"])),
    })


@router.get("/vinculacion/", name="titulatec.pages.vinculacion.home")
async def vinculacion_home(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.dashboard.vinculacion"])),
):
    return render_titulatec(request, "titulatec/role_home.html", {
        "role_label": "Vinculación",
        "first_name": _first_name(int(user["sub"])),
    })
