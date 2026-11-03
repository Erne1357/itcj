"""Vista del alumno: su credencial (/credencial/), su foto oficial y el QR rotatorio.

Sin permisos por alumno: basta la sesión y tener nº de control (regla del shell).
Ningún QR ni token sale para una cuenta inactiva o sin foto.
"""
import logging
from datetime import datetime, timezone

import segno
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from itcj2.dependencies import DbSession, OptionalUser, is_global_admin, require_page_login
from itcj2.exceptions import PageForbidden, PageLoginRequired

router = APIRouter(tags=["credencial-student"])
logger = logging.getLogger(__name__)

_NO_STORE = {"Cache-Control": "no-store"}


def _verify_base(request: Request) -> str:
    """Origen del enlace del QR. En prod nginx escucha :80 tras TLS externo, así que
    request.base_url diría http://: se usa el dominio oficial (el que muestra la página)."""
    from itcj2.config import get_settings

    settings = get_settings()
    if settings.FLASK_ENV == "production":
        return settings.DOMAIN.rstrip("/")
    return str(request.base_url).rstrip("/")


def _can_open_panel(db, user: dict) -> bool:
    if is_global_admin(user):
        return True
    from itcj2.core.services.authz_cache import cached_perms
    try:
        return "credencial.admin.page.view" in cached_perms(db, int(user["sub"]), "credencial")
    except HTTPException:  # app credencial ausente o inactiva
        return False


@router.get("/", response_class=HTMLResponse)
def student_card(request: Request, user: dict = Depends(require_page_login), db: DbSession = None):
    from itcj2.apps.credencial.pages.render import render_credencial
    from itcj2.apps.credencial.services.card_service import CardService, short_name
    from itcj2.apps.credencial.services.token_service import TOKEN_REFRESH_SECONDS, TOKEN_TTL_SECONDS
    from itcj2.core.models.user import User
    from itcj2.core.utils.timezone import APP_TIMEZONE

    uid = int(user["sub"])
    card = CardService.build(db, uid)
    if card is None:
        if _can_open_panel(db, user):
            return RedirectResponse("/credencial/admin/", status_code=302)
        raise PageForbidden(has_app_access=False)
    student = db.get(User, uid)
    if not student.is_active:  # cookie viva de una cuenta desactivada: la sesión ya no vale
        raise PageLoginRequired()
    return render_credencial(request, "credencial/student.html", {
        "card": card,
        "short_name": short_name(student),
        "tz": APP_TIMEZONE,
        "ttl_s": TOKEN_TTL_SECONDS,
        "refresh_s": TOKEN_REFRESH_SECONDS,
    })


@router.get("/qr", response_class=HTMLResponse)
def student_qr(request: Request, user: OptionalUser, db: DbSession):
    """Parcial HTMX con el QR vigente. 409 sin foto (sin token), 403 inactiva o sin tarjeta.

    Se sondea cada 30 s: solo mira usuario, foto y archivo (no arma la tarjeta completa).
    """
    from itcj2.apps.credencial.models import CredentialPhoto
    from itcj2.apps.credencial.pages.render import render_credencial
    from itcj2.apps.credencial.services.photo_service import PhotoService
    from itcj2.apps.credencial.services.token_service import TOKEN_TTL_SECONDS, CredentialTokenService
    from itcj2.core.models.user import User

    if not user:  # HTMX seguiría un 302 y metería el login dentro del recuadro del QR
        return Response(status_code=401, headers={**_NO_STORE, "HX-Redirect": "/itcj/login"})
    uid = int(user["sub"])
    student = db.get(User, uid)
    if student is None or student.control_number is None or not student.is_active:
        return Response(status_code=403, headers=_NO_STORE)
    photo = db.get(CredentialPhoto, uid)
    if not PhotoService.has_file(photo):
        resp = render_credencial(request, "credencial/partials/_qr.html", {"pending": True}, status_code=409)
    else:
        now = datetime.now(timezone.utc)
        token = CredentialTokenService.issue(photo.ref, now=now)
        svg = segno.make(f"{_verify_base(request)}/credencial/v/{token}", error="m", micro=False).svg_inline(
            dark="#000", light="#fff", border=4, omitsize=True,
            svgclass="cc-qr__svg", lineclass=None, title="Código QR de verificación",
        )
        expires_at = datetime.fromtimestamp(int(now.timestamp()) + TOKEN_TTL_SECONDS, timezone.utc)
        resp = render_credencial(request, "credencial/partials/_qr.html",
                                 {"svg": svg, "expires_at": expires_at.isoformat()})
    resp.headers.update(_NO_STORE)
    return resp


@router.get("/foto")
def own_photo(user: dict = Depends(require_page_login), db: DbSession = None):
    from itcj2.apps.credencial.models import CredentialPhoto
    from itcj2.apps.credencial.services.photo_service import PHOTO_MIME, PhotoService

    photo = db.get(CredentialPhoto, int(user["sub"]))
    if photo is None:
        raise HTTPException(status_code=404, detail="Sin foto oficial")
    try:
        data = PhotoService.read_bytes(photo)
    except OSError:
        raise HTTPException(status_code=404, detail="Sin foto oficial")
    return Response(data, media_type=PHOTO_MIME, headers={"Cache-Control": "private, no-store"})
