"""Páginas de consulta de Cámaras: lista, revelar y cambio de contraseña (HTMX).

Los secretos solo salen en el fragmento de revelar (no-store); la lista y el
formulario nunca los llevan.
"""
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from itcj2.apps.cameras.pages.render import render_cameras
from itcj2.apps.cameras.services import dvr_service, secrets
from itcj2.database import get_db
from itcj2.dependencies import require_page_login
from itcj2.exceptions import PageForbidden

logger = logging.getLogger(__name__)
router = APIRouter()


def _gate(request: Request, user: dict = Depends(require_page_login),
          db: Session = Depends(get_db)):
    """Login + no-alumno + permiso de página. Devuelve el usuario o un redirect."""
    if user.get("cn"):
        return RedirectResponse("/itcj/m/", status_code=302)
    if user.get("role") != "admin":
        from itcj2.core.services.authz_cache import cached_has_assignment, cached_perms
        uid = int(user["sub"])
        if not cached_has_assignment(db, uid, dvr_service.APP):
            raise PageForbidden(has_app_access=False)
        if dvr_service.PERM_PAGE not in cached_perms(db, uid, dvr_service.APP):
            raise PageForbidden(has_app_access=True)
    return user


def _cam_error(resp, message: str):
    """Error de dominio en header, percent-encoded (ASCII puro)."""
    resp.headers["X-Cam-Error"] = quote(message, safe="")
    return resp


def _list_ctx(db: Session, user: dict, q: str | None) -> dict:
    viewer = dvr_service.viewer_for(db, user)
    dvrs = dvr_service.list_visible(db, viewer, q)
    groups: dict[str, list] = {}
    for d in dvrs:
        groups.setdefault(d.location or "Sin ubicación", []).append(d)
    return {"viewer": viewer, "groups": list(groups.items()), "q": q or ""}


@router.get("/")
def index(request: Request, q: str = "", user=Depends(_gate), db: Session = Depends(get_db)):
    if isinstance(user, RedirectResponse):
        return user
    return render_cameras(request, "cameras/index.html", _list_ctx(db, user, q or None))


@router.get("/list")
def list_partial(request: Request, q: str = "", user=Depends(_gate),
                 db: Session = Depends(get_db)):
    if isinstance(user, RedirectResponse):
        return user
    return render_cameras(request, "cameras/partials/list.html", _list_ctx(db, user, q or None))


def _visible_or_none(db, user, dvr_id):
    viewer = dvr_service.viewer_for(db, user)
    return viewer, dvr_service.get_visible(db, viewer, dvr_id)


def _slot_headers(resp, dvr_id: int):
    """Errores del formulario: se pintan en el hueco, sin tocar la tarjeta."""
    resp.headers["HX-Retarget"] = f"#cam-pwslot-{dvr_id}"
    resp.headers["HX-Reswap"] = "innerHTML"
    return resp


def _not_found(request, dvr_id: int | None = None):
    """Mismo mensaje exista o no el DVR (no revela existencia).

    Navegación directa (sin HX-Request): página completa con la base.
    """
    if not request.headers.get("HX-Request"):
        return _cam_error(render_cameras(request, "cameras/not_found_page.html", status_code=404),
                          "No encontrado.")
    resp = _cam_error(render_cameras(request, "cameras/partials/not_found.html",
                                     status_code=404), "No encontrado.")
    return _slot_headers(resp, dvr_id) if dvr_id else resp


@router.post("/dvrs/{dvr_id}/reveal")
def reveal(dvr_id: int, request: Request, user=Depends(_gate), db: Session = Depends(get_db)):
    if isinstance(user, RedirectResponse):
        return user
    viewer, dvr = _visible_or_none(db, user, dvr_id)
    if dvr is None:
        return _not_found(request)
    try:
        rv = dvr_service.reveal(db, dvr, int(user["sub"]))
    except secrets.CamerasDecryptError:  # antes que su clase base
        msg = "No se pudo descifrar: la llave de cifrado no coincide."
    except secrets.CamerasKeyMissing:
        msg = "Falta configurar la llave de cifrado."
    else:
        resp = render_cameras(request, "cameras/partials/revealed.html",
                              {"d": dvr, "rv": rv, "viewer": viewer})
        resp.headers["Cache-Control"] = "no-store"
        return resp
    resp = render_cameras(request, "cameras/partials/card_secret.html",
                          {"d": dvr, "error": msg}, status_code=503)
    return _cam_error(resp, msg)


def _pw_form(request, dvr, *, error=None, status_code=200):
    resp = render_cameras(request, "cameras/partials/password_form.html",
                          {"d": dvr, "error": error}, status_code=status_code)
    if not error:
        return resp
    return _slot_headers(_cam_error(resp, error), dvr.id)


@router.get("/dvrs/{dvr_id}/password")
def password_form(dvr_id: int, request: Request, user=Depends(_gate),
                  db: Session = Depends(get_db)):
    if isinstance(user, RedirectResponse):
        return user
    viewer, dvr = _visible_or_none(db, user, dvr_id)
    if dvr is None or not (viewer.can_update_password or viewer.can_manage):
        return _not_found(request, dvr_id)
    return _pw_form(request, dvr)


@router.post("/dvrs/{dvr_id}/password")
def password_save(dvr_id: int, request: Request, password: str = Form(""),
                  password_confirm: str = Form(""), user=Depends(_gate),
                  db: Session = Depends(get_db)):
    if isinstance(user, RedirectResponse):
        return user
    viewer, dvr = _visible_or_none(db, user, dvr_id)
    if dvr is None or not (viewer.can_update_password or viewer.can_manage):
        return _not_found(request, dvr_id)
    if password != password_confirm:
        return _pw_form(request, dvr, error="No coincide con la contraseña nueva.", status_code=422)
    try:
        ok = dvr_service.set_password(db, viewer, dvr_id, password, int(user["sub"]))
    except ValueError as exc:
        return _pw_form(request, dvr, error=str(exc), status_code=422)
    except secrets.CamerasKeyMissing:
        return _pw_form(request, dvr, error="Falta configurar la llave de cifrado.", status_code=503)
    if not ok:
        return _not_found(request, dvr_id)
    db.refresh(dvr)
    return render_cameras(request, "cameras/partials/card.html", {"d": dvr, "viewer": viewer})
