"""Unirse al módulo de Prórrogas: QR y enlace de invitación (ambos pasan por Aceptar).

Rutas públicas (sin ``require_page_app``: quien se une todavía no tiene el rol).
El token viaja en la URL, así que toda respuesta lleva ``Referrer-Policy: no-referrer``
y ni el token ni el NIP se escriben en logs.
"""
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from itcj2.apps.prorrogas_tec.services import invitation_service as inv
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.identity import nombre_corto
from itcj2.dependencies import DbSession
from itcj2.templates import render

SOLICITUD = "/prorrogas/estudiante/solicitud"
_HEADERS = {"Referrer-Policy": "no-referrer"}

router = APIRouter(prefix="/unirse", tags=["prorrogas_tec-pages-unirse"])


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=302, headers=_HEADERS)


def _login_url(next_path: str) -> str:
    return f"/itcj/login?next={quote(next_path, safe='')}"


def _login(next_path: str) -> RedirectResponse:
    return _redirect(_login_url(next_path))


def _page(request, template, context, status=200):
    resp = render(request, f"prorrogas_tec/estudiante/{template}", context, status_code=status)
    resp.headers.update(_HEADERS)
    return resp


def _error(request, message, status, qr=False):
    return _page(request, "unirse_error.html", {"title": "Prórrogas · Unirse", "message": message, "qr": qr}, status)


def _user_id(request) -> int | None:
    payload = getattr(request.state, "current_user", None)
    return int(payload["sub"]) if payload else None


def _qr_error(request, e: ServiceError):
    if e.code == "cuenta_sin_numero_de_control":
        return _error(request, e.message, e.status)
    return _error(request, e.message, e.status, qr=True)  # vencido o alterado: los mismos pasos para pedir otro


@router.get("", name="prorrogas_tec.pages.unirse.qr")
def unirse_qr(request: Request, db: DbSession, t: str = ""):
    uid = _user_id(request)
    if uid is None:  # el login regresa aquí con el mismo token
        return _login(f"/prorrogas/unirse?t={t}")
    try:  # se valida antes de preguntar: un QR vencido o una cuenta de personal no ven el botón
        inv.read_qr(t)
        user = inv.joinable_student(db, uid)
    except ServiceError as e:
        return _qr_error(request, e)
    return _page(request, "unirse_aceptar.html", {"title": "Prórrogas · Unirse", "token": t,
                                                   "nombre": user.full_name, "control": user.control_number,
                                                   "nombre_corto": nombre_corto(user.first_name, user.last_name)})


@router.post("", name="prorrogas_tec.pages.unirse.aceptar")
def unirse_aceptar(request: Request, db: DbSession, t: str = Form("")):
    uid = _user_id(request)
    if uid is None:  # la sesión venció entre ver la pregunta y aceptar
        return _login(f"/prorrogas/unirse?t={t}")
    try:
        inv.join(db, uid, via="qr", issued_by_id=inv.read_qr(t))
    except ServiceError as e:
        return _qr_error(request, e)
    return _redirect(SOLICITUD)


@router.get("/invitacion/{token}", name="prorrogas_tec.pages.unirse.invitacion")
def unirse_invitacion(request: Request, db: DbSession, token: str):
    try:
        invitacion = inv.validate_invitation(db, token)
    except ServiceError as e:
        return _error(request, e.message, e.status)
    uid = _user_id(request)
    if uid is None:
        if not invitacion.user.password_hash:
            return _error(request, inv.SIN_NIP, 403)
        return _login(f"/prorrogas/unirse/invitacion/{token}")
    if uid != invitacion.user_id:
        return _error(request, "Esta invitación es de otra cuenta.", 403)
    user = invitacion.user
    return _page(request, "unirse_aceptar.html", {"title": "Prórrogas · Unirse", "token": token,
                                                   "nombre": user.full_name, "control": user.control_number,
                                                   "nombre_corto": nombre_corto(user.first_name, user.last_name)})


@router.post("/invitacion/{token}", name="prorrogas_tec.pages.unirse.invitacion_aceptar")
def unirse_invitacion_aceptar(request: Request, db: DbSession, token: str):
    uid = _user_id(request)
    if uid is None:  # la sesión venció entre ver la pregunta y aceptar
        return _login(f"/prorrogas/unirse/invitacion/{token}")
    try:
        inv.consume_invitation(db, token, user_id=uid)
    except ServiceError as e:
        return _error(request, e.message, e.status)
    return _redirect(SOLICITUD)
