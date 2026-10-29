"""Unirse al módulo de Prórrogas: QR, enlace de invitación y "Crea tu NIP".

Rutas públicas (sin ``require_page_app``: quien se une todavía no tiene el rol).
El token viaja en la URL, así que toda respuesta lleva ``Referrer-Policy: no-referrer``
y ni el token ni el NIP se escriben en logs.
"""
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from itcj2.apps.prorrogas_tec.services import invitation_service as inv
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.core.utils.timezone import db_now
from itcj2.dependencies import DbSession
from itcj2.templates import render

SOLICITUD = "/prorrogas/estudiante/solicitud"
_QR_MENSAJE = "Este código ya no es válido. Pide un código nuevo en la Subdirección Académica."
_HEADERS = {"Referrer-Policy": "no-referrer"}

router = APIRouter(prefix="/unirse", tags=["prorrogas_tec-pages-unirse"])


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=302, headers=_HEADERS)


def _login(next_path: str) -> RedirectResponse:
    return _redirect(f"/itcj/login?next={quote(next_path, safe='')}")


def _page(request, template, context, status=200):
    resp = render(request, f"prorrogas_tec/estudiante/{template}", context, status_code=status)
    resp.headers.update(_HEADERS)
    return resp


def _error(request, message, status):
    return _page(request, "unirse_error.html", {"title": "Prórrogas · Unirse", "message": message}, status)


def _user_id(request) -> int | None:
    payload = getattr(request.state, "current_user", None)
    return int(payload["sub"]) if payload else None


@router.get("", name="prorrogas_tec.pages.unirse.qr")
async def unirse_qr(request: Request, db: DbSession, t: str = ""):
    uid = _user_id(request)
    if uid is None:
        return _login(f"/prorrogas/unirse?t={t}")
    try:
        by = inv.read_qr(t)
        inv.join(db, uid, via="qr", issued_by_id=by)
    except ServiceError as e:
        return _error(request, _QR_MENSAJE, e.status)
    return _redirect(SOLICITUD)


def _nip_form(request, token, status=200, error=None):
    return _page(request, "crea_nip.html", {"title": "Prórrogas · Crea tu NIP", "token": token, "error": error}, status)


@router.get("/invitacion/{token}", name="prorrogas_tec.pages.unirse.invitacion")
async def unirse_invitacion(request: Request, db: DbSession, token: str):
    invitacion = inv.invitation_for_token(db, token)
    if invitacion is None:
        return _error(request, "La invitación no es válida.", 404)
    if invitacion.used_at is not None:
        return _error(request, "Esta invitación ya se usó.", 409)
    uid = _user_id(request)
    if uid is None and not invitacion.user.password_hash:
        # Cuenta nueva sin sesión: aún no puede iniciarla, así que crea su NIP primero.
        if invitacion.expires_at is None or db_now() >= invitacion.expires_at:
            return _error(request, "La invitación venció. Pide otra.", 410)
        return _nip_form(request, token)
    if uid is None:
        return _login(f"/prorrogas/unirse/invitacion/{token}")
    try:
        inv.consume_invitation(db, token, user_id=uid)
    except ServiceError as e:
        return _error(request, e.message, e.status)
    return _redirect(SOLICITUD)


@router.post("/invitacion/{token}", name="prorrogas_tec.pages.unirse.crear_nip")
async def unirse_crear_nip(request: Request, db: DbSession, token: str,
                           nip: str = Form(""), nip2: str = Form("")):
    try:
        inv.set_initial_nip(db, token, nip, nip2)
    except ServiceError as e:
        if e.status == 400:
            return _nip_form(request, token, 400, e.message)
        if e.code != "cuenta_con_nip":  # inválida, usada o vencida
            return _error(request, e.message, e.status)
    return _login(f"/prorrogas/unirse/invitacion/{token}")
