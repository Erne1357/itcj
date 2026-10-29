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

# En orden de prioridad: el primer rol que tenga el usuario decide su destino.
# (Antes se tomaba un rol cualquiera del conjunto, así que con secretaria y
# admin a la vez el destino dependía del orden en que los devolvía la BD.)
_ROLE_HOME: tuple[tuple[str, str], ...] = (
    ("secretaria", "/prorrogas/secretaria"),
    # El admin de la app tiene los permisos de la secretaria (04_insert_secretaria.sql).
    # /prorrogas/admin/* es la vista vieja del fork; el Plan 2 la elimina (spec §12).
    ("admin",      "/prorrogas/secretaria"),
    ("student",    "/prorrogas/student/home"),
)


@router.get("/", name="prorrogas_tec.pages.landing.home")
async def home(
    request: Request,
    user: dict = Depends(require_page_login),
):
    """Redirige a la vista que le toca al usuario según sus roles en la app."""
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.database import SessionLocal

    user_id = int(user["sub"])
    db = SessionLocal()
    try:
        roles = user_roles_in_app(db, user_id, "prorrogas_tec")
    finally:
        db.close()
    destination = next((url for role, url in _ROLE_HOME if role in roles), "/prorrogas/student/home")
    logger.debug("Redirigiendo usuario %s (roles=%s) a %s", user_id, sorted(roles), destination)
    return RedirectResponse(destination, status_code=302)
