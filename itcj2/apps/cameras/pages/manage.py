"""Páginas de gestión de Cámaras (alta/edición/baja de DVR) y bitácora.

Los formularios son de solo escritura: nunca devuelven contraseña, patrón, usuario
ni notas. Un error de dominio se pinta en el mismo formulario (422/503 con X-Cam-Error)
conservando lo capturado, salvo los secretos.
"""
import logging
import math
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from itcj2.apps.cameras.pages.render import render_cameras
from itcj2.apps.cameras.pages.viewer import _cam_error, _gate, _not_found, _visible_or_none
from itcj2.apps.cameras.schemas.dvr import DvrInput
from itcj2.apps.cameras.services import dvr_service, secrets
from itcj2.database import get_db
from itcj2.exceptions import PageForbidden

logger = logging.getLogger(__name__)
router = APIRouter()

PER_PAGE = 50
ACTION_LABELS = {
    "reveal": "Vio credenciales",
    "extend": "Extendió el tiempo",
    "create": "Registró el DVR",
    "update": "Editó los datos",
    "password_update": "Cambió la contraseña",
    "pattern_update": "Cambió el patrón",
    "departments_update": "Cambió los departamentos",
    "deactivate": "Dio de baja el DVR",
    "reactivate": "Reactivó el DVR",
}
_FIELD_LABELS = {"name": "nombre", "location": "ubicación", "brand": "marca", "model": "modelo",
                 "channels": "canales", "camera_type": "tipo de cámaras",
                 "cameras_installed": "cámaras instaladas", "username": "usuario", "notes": "notas"}


def _manage_gate(request: Request, user=Depends(_gate), db: Session = Depends(get_db)):
    """Login + permiso de página + gestión. Devuelve (user, viewer) o un redirect."""
    if isinstance(user, RedirectResponse):
        return user
    viewer = dvr_service.viewer_for(db, user)
    if not viewer.can_manage:
        raise PageForbidden(has_app_access=True)
    return user, viewer


def _inactive_gate(gate=Depends(_manage_gate)):
    """Dados de baja no pasan por get_visible: solo quien ve todos los DVR."""
    if not isinstance(gate, RedirectResponse) and not gate[1].see_all:
        raise PageForbidden(has_app_access=True)
    return gate


def _audit_gate(request: Request, user=Depends(_gate), db: Session = Depends(get_db)):
    if isinstance(user, RedirectResponse):
        return user
    viewer = dvr_service.viewer_for(db, user)
    if not viewer.can_audit:
        raise PageForbidden(has_app_access=True)
    return user, viewer


def _departments(db: Session) -> list:
    from itcj2.core.models.department import Department
    return db.query(Department).filter(Department.is_active.is_(True)).order_by(Department.name).all()


def _form_ctx(db, viewer, dvr, values=None, selected=None, error=None):
    v = values or {}
    deps = _departments(db)
    if dvr:  # los ya ligados siguen visibles (marcados) aunque estén inactivos
        known = {x.id for x in deps}
        deps = sorted(deps + [x for x in dvr.departments if x.id not in known], key=lambda x: x.name)
    return {
        "viewer": viewer, "d": dvr, "error": error, "v": v,
        "departments": deps,
        "selected": set(selected if selected is not None
                        else ([x.id for x in dvr.departments] if dvr else [])),
        "locations": sorted({x.location for x in dvr_service.list_visible(db, viewer) if x.location}),
        "has_password": bool(dvr and dvr.password_cipher),
        "has_pattern": bool(dvr and dvr.pattern_cipher),
    }


def _values_of(dvr):
    return {k: ("" if getattr(dvr, k) is None else getattr(dvr, k))
            for k in ("name", "location", "brand", "model", "channels",
                      "camera_type", "cameras_installed")} if dvr else {}


def _form_page(request, db, viewer, dvr):
    ctx = _form_ctx(db, viewer, dvr, _values_of(dvr))
    return render_cameras(request, "cameras/manage_form.html", ctx)


def _form_error(request, db, viewer, dvr, values, selected, message, status_code):
    """Error del servidor sin destruir lo tecleado.

    HTMX: solo el aviso, redirigido a #cam-form-error (patrón y contraseñas siguen en el DOM).
    Sin HTMX: página completa con lo capturado (sin secretos) y el aviso en el formulario.
    """
    if request.headers.get("HX-Request"):
        resp = render_cameras(request, "cameras/partials/form_error.html", {"error": message},
                              status_code=status_code)
        resp.headers["HX-Retarget"] = "#cam-form-error"
        resp.headers["HX-Reswap"] = "innerHTML"
    else:
        resp = render_cameras(request, "cameras/manage_form.html",
                              _form_ctx(db, viewer, dvr, values, selected, message), status_code=status_code)
    return _cam_error(resp, message)


def _done(request: Request, to: str = "/cameras/"):
    if request.headers.get("HX-Request"):
        resp = Response(status_code=200)
        resp.headers["HX-Redirect"] = to
        return resp
    return RedirectResponse(to, status_code=303)


async def _parse(request: Request):
    """Lee el formulario crudo: (DvrInput, values, selected) o lanza ValueError."""
    form = await request.form()
    g = lambda k: form.get(k) or ""  # noqa: E731
    values = {k: g(k).strip() for k in ("name", "location", "brand", "model", "channels",
                                   "camera_type", "cameras_installed")}
    selected = []
    for raw in form.getlist("department_ids"):
        try:
            selected.append(int(raw))
        except ValueError:
            raise ValueError("Departamento no válido.") from None
    return form, values, selected


def _build(form, values, selected) -> DvrInput:
    """Arma el DvrInput; el mensaje de error nunca lleva valores capturados."""
    password = form.get("password") or None  # sin strip: se guarda como se tecleó
    if (form.get("password") or "") != (form.get("password_confirm") or ""):
        raise ValueError("La confirmación no coincide con la contraseña.")
    try:
        channels = int(values["channels"]) if values["channels"] else None
    except ValueError:
        raise ValueError("Los canales deben ser un número.") from None
    try:
        installed = int(values["cameras_installed"]) if values["cameras_installed"] else None
    except ValueError:
        raise ValueError("Las cámaras instaladas deben ser un número.") from None
    try:
        return DvrInput(
            name=values["name"], location=values["location"] or None, brand=values["brand"] or None,
            model=values["model"] or None, channels=channels,
            camera_type=values["camera_type"] or None, cameras_installed=installed,
            username=form.get("username") or None, notes=form.get("notes") or None,
            remove_username=bool(form.get("remove_username")), remove_notes=bool(form.get("remove_notes")),
            department_ids=selected, password=password,
            remove_password=bool(form.get("remove_password")),
            pattern=(form.get("pattern") or "").strip() or None,
            remove_pattern=bool(form.get("remove_pattern")),
        )
    except ValidationError as exc:
        err = exc.errors()[0]
        if not err["loc"]:  # validador de modelo (cámaras > canales): su mensaje es de ventanilla
            raise ValueError(str(err["msg"]).removeprefix("Value error, ")) from None
        loc = ".".join(str(p) for p in err["loc"])
        raise ValueError(f"Revisa el campo «{_FIELD_LABELS.get(loc, loc)}».") from None


async def _save(request, db, viewer, user, dvr):
    """Alta (dvr None) o edición. Devuelve la respuesta."""
    try:
        form, values, selected = await _parse(request)
    except ValueError as exc:
        return _form_error(request, db, viewer, dvr, {}, [], str(exc), 422)
    try:
        data = _build(form, values, selected)
        if dvr is None:
            saved = dvr_service.create(db, data, int(user["sub"]))
            ok = "registrado"
        else:
            saved = dvr_service.update(db, dvr, data, int(user["sub"]))
            ok = "actualizado"
        target = f"/cameras/?ok={ok}&dvr={int(saved.id)}"
    except ValueError as exc:
        db.rollback()
        return _form_error(request, db, viewer, dvr, values, selected, str(exc), 422)
    except secrets.CamerasKeyMissing:
        return _form_error(request, db, viewer, dvr, values, selected,
                           "Falta configurar la llave de cifrado.", 503)
    except Exception as exc:
        logger.error("Error guardando DVR (%s)", type(exc).__name__)  # sin traceback: podría llevar datos
        db.rollback()
        return _form_error(request, db, viewer, dvr, values, selected, "Error interno al guardar.", 500)
    return _done(request, target)


@router.get("/dvrs/new")
def new_form(request: Request, gate=Depends(_manage_gate), db: Session = Depends(get_db)):
    if isinstance(gate, RedirectResponse):
        return gate
    return _form_page(request, db, gate[1], None)


@router.post("/dvrs")
async def create_dvr(request: Request, gate=Depends(_manage_gate), db: Session = Depends(get_db)):
    if isinstance(gate, RedirectResponse):
        return gate
    return await _save(request, db, gate[1], gate[0], None)


@router.get("/dvrs/{dvr_id}/edit")
def edit_form(dvr_id: int, request: Request, gate=Depends(_manage_gate), db: Session = Depends(get_db)):
    if isinstance(gate, RedirectResponse):
        return gate
    user, viewer = gate
    _, dvr = _visible_or_none(db, user, dvr_id)
    if dvr is None:
        return _not_found(request)
    return _form_page(request, db, viewer, dvr)


@router.post("/dvrs/{dvr_id}")
async def update_dvr(dvr_id: int, request: Request, gate=Depends(_manage_gate),
                     db: Session = Depends(get_db)):
    if isinstance(gate, RedirectResponse):
        return gate
    user, viewer = gate
    _, dvr = _visible_or_none(db, user, dvr_id)
    if dvr is None:
        return _not_found(request)
    return await _save(request, db, viewer, user, dvr)


@router.post("/dvrs/{dvr_id}/deactivate")
def deactivate_dvr(dvr_id: int, request: Request, gate=Depends(_manage_gate),
                   db: Session = Depends(get_db)):
    if isinstance(gate, RedirectResponse):
        return gate
    user, _viewer = gate
    _, dvr = _visible_or_none(db, user, dvr_id)
    if dvr is None:
        return _not_found(request)
    dvr_service.deactivate(db, dvr, int(user["sub"]))
    return _done(request, "/cameras/?ok=baja")


@router.get("/inactive")
def inactive(request: Request, gate=Depends(_inactive_gate), db: Session = Depends(get_db)):
    if isinstance(gate, RedirectResponse):
        return gate
    return render_cameras(request, "cameras/inactive.html",
                          {"viewer": gate[1], "items": dvr_service.list_inactive(db)})


@router.post("/dvrs/{dvr_id}/reactivate")
def reactivate_dvr(dvr_id: int, request: Request, gate=Depends(_inactive_gate),
                   db: Session = Depends(get_db)):
    if isinstance(gate, RedirectResponse):
        return gate
    user, _viewer = gate
    dvr = dvr_service.get_inactive(db, dvr_id)
    if dvr is None:
        return _not_found(request)
    dvr_service.reactivate(db, dvr, int(user["sub"]))
    return _done(request, f"/cameras/?ok=reactivado&dvr={int(dvr_id)}")


# === BITÁCORA ===

def _opt_int(v: str | None) -> int | None:
    try:
        return int(v) if v else None
    except ValueError:
        return None


def _detail_text(row: dict) -> str:
    d = row.get("detail") or {}
    if d.get("fields"):
        return "Campos: " + ", ".join(_FIELD_LABELS.get(f, f) for f in d["fields"])
    if d.get("removed"):
        return "Se quitó"
    if "departments" in d:
        n = len(d["departments"])
        return "Sin departamento" if n == 0 else ("1 departamento" if n == 1 else f"{n} departamentos")
    return ""


def _opt_date(v: str | None) -> date | None:
    """YYYY-MM-DD; cualquier otra cosa se ignora."""
    try:
        d = date.fromisoformat(v) if v and len(v) == 10 else None
    except ValueError:
        return None
    # hasta + 1 día desborda en el último día representable; fuera de rango = inválido
    return d if d and date(1900, 1, 1) <= d < date(9999, 1, 1) else None


def _reveal_label(detail: dict | None) -> str:
    """Qué entregó el revelado; filas viejas (sin detail) quedan como «Vio credenciales»."""
    if not detail or "pattern" not in detail:
        return ACTION_LABELS["reveal"]
    pat, pwd = bool(detail.get("pattern")), bool(detail.get("password"))
    if pat and pwd:
        return "Vio patrón y contraseña"
    if pwd:
        return "Vio la contraseña"
    if pat:
        return "Vio el patrón"
    return "Vio el DVR (sin datos guardados)"


def _audit_ctx(db, viewer, page, dvr_id, actor_id, action, desde=None, hasta=None):
    if action not in ACTION_LABELS:
        action = None
    if desde and hasta and desde > hasta:
        desde, hasta = hasta, desde
    rows, total = dvr_service.audit_page(db, page=page, per_page=PER_PAGE, dvr_id=dvr_id,
                                         actor_id=actor_id, action=action, desde=desde, hasta=hasta)
    for r in rows:
        r["label"] = (_reveal_label(r["detail"]) if r["action"] == "reveal"
                      else ACTION_LABELS.get(r["action"], r["action"]))
        r["text"] = _detail_text(r)
    return {"viewer": viewer, "rows": rows, "total": total, "page": page,
            "total_pages": max(1, math.ceil(total / PER_PAGE)),
            "f": {"dvr_id": dvr_id or "", "actor_id": actor_id or "", "action": action or "",
                  "desde": desde.isoformat() if desde else "", "hasta": hasta.isoformat() if hasta else ""},
            "actions": ACTION_LABELS}


@router.get("/audit")
def audit(request: Request, page: str = "1", dvr_id: str = "", actor_id: str = "", action: str = "",
          desde: str = "", hasta: str = "", gate=Depends(_audit_gate), db: Session = Depends(get_db)):
    if isinstance(gate, RedirectResponse):
        return gate
    ctx = _audit_ctx(db, gate[1], max(_opt_int(page) or 1, 1), _opt_int(dvr_id),
                     _opt_int(actor_id), action or None, _opt_date(desde), _opt_date(hasta))
    if request.headers.get("HX-Request"):
        return render_cameras(request, "cameras/partials/audit_rows.html", ctx)
    from itcj2.apps.cameras.models import Dvr
    ctx["actor_options"] = dvr_service.audit_actors(db)
    ctx["dvr_options"] = [(i, n) for i, n in db.query(Dvr.id, Dvr.name).order_by(Dvr.name).all()]
    return render_cameras(request, "cameras/audit.html", ctx)
