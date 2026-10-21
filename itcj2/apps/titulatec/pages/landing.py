"""Landing de TitulaTec — redirige al dashboard según el rol del usuario."""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import (
    _NAV_PHASE_GATE, get_titulatec_roles, resolve_dashboard_url,
)

logger = logging.getLogger("itcj2.apps.titulatec.pages.landing")

router = APIRouter(tags=["titulatec-pages-landing"])


@router.get("/", name="titulatec.pages.landing")
def landing(
    request: Request,
    user: dict = Depends(require_page_app("titulatec")),
):
    """Redirige al dashboard correspondiente al rol del usuario en la app."""
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.database import SessionLocal

    uid = int(user["sub"])
    roles = get_titulatec_roles(uid)
    # Mismos permisos que el gate (`cached_perms`): el tablero solo si los tiene.
    # Si falla la lectura, set vacío = Bandeja (nunca un 403 por aterrizar mal).
    # Las fases que hoy se operan (ruling R5 de la fase 4): un aterrizaje
    # condicional (Titulación, Sinodales) exige además su fase; si el catálogo
    # no se puede leer, ninguna (el aterrizaje de siempre).
    db = SessionLocal()
    try:
        try:
            perms = set(cached_perms(db, uid, "titulatec"))
        except Exception as exc:
            logger.warning("Error obteniendo permisos titulatec para el landing (user %s): %s",
                           uid, exc)
            perms = set()
        try:
            operable = PhaseService.operable_codes(db, set(_NAV_PHASE_GATE.values()))
        except Exception as exc:
            logger.warning("Error leyendo el catálogo de fases para el landing (user %s): %s",
                           uid, exc)
            operable = set()
    finally:
        db.close()
    url = resolve_dashboard_url(roles, jwt_role=user.get("role"), perms=perms, operable=operable)
    return RedirectResponse(url, status_code=302)
