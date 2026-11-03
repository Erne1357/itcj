"""Página PÚBLICA de verificación del QR: /credencial/v/{token} (sin login).

Requisitos duros (spec §6): cero datos en vencido/no válido, rate limit por IP,
cabeceras anti-caché/anti-indexado en TODA respuesta, foto incrustada (no hay ruta
de foto pública). La vista completa (nº de control + bitácora) es solo para quien
trae sesión y el permiso; un alumno con sesión ve la vista pública.
"""
import logging
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from itcj2.dependencies import DbSession, OptionalUser, is_global_admin

router = APIRouter(tags=["credencial-public"])
logger = logging.getLogger(__name__)

_PUBLIC_HEADERS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
}
_STATUS_CODE = {"valid": 200, "inactive": 200, "expired": 404, "invalid": 404}


def _can_see_full(db, user: dict | None) -> bool:
    if not user:
        return False
    if is_global_admin(user):
        return True
    from itcj2.core.services.authz_cache import cached_perms
    try:
        return "credencial.verify.page.full" in cached_perms(db, int(user["sub"]), "credencial")
    except HTTPException:  # app credencial ausente/inactiva: nadie tiene vista completa
        return False


@router.get("/v/{token}", response_class=HTMLResponse)
def verify(token: str, request: Request, user: OptionalUser, db: DbSession):
    from itcj2.apps.credencial.pages.render import render_credencial
    from itcj2.apps.credencial.services.verification_service import VerificationService
    from itcj2.config import get_settings
    from itcj2.core.utils.client_ip import client_ip
    from itcj2.core.utils.rate_limit import check_and_count
    from itcj2.core.utils.timezone import APP_TIMEZONE

    tz = ZoneInfo(APP_TIMEZONE)
    ctx = {"domain": urlparse(get_settings().DOMAIN).hostname or get_settings().DOMAIN}

    allowed, retry_after = check_and_count("credencial-verify", client_ip(request), limit=30, window=60)
    if not allowed:
        resp = render_credencial(request, "credencial/verify.html", {**ctx, "state": "limited"}, status_code=429)
        resp.headers["Retry-After"] = str(retry_after)
    else:
        result = VerificationService.resolve(db, token)
        ctx.update(state=result.status, **VerificationService.public_view(db, result))
        if result.student is not None:
            ctx["verified_at"] = datetime.now(tz).strftime("%H:%M:%S")
            ctx["issued_at"] = result.issued_at.astimezone(tz).strftime("%H:%M:%S")
            if _can_see_full(db, user):
                VerificationService.record(db, result, int(user["sub"]))
                ctx.update(control_number=result.student.control_number, logged=True)
        resp = render_credencial(request, "credencial/verify.html", ctx, status_code=_STATUS_CODE[result.status])

    resp.headers.update(_PUBLIC_HEADERS)
    return resp
