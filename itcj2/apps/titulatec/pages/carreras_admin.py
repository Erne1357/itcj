"""Pestaña «Carreras por departamento» (spec 2026-10-21 fase 4 §13, D10, R-C, R-F, R-G).

Solo `admin`: abrir exige `program_department.page.list` y guardar
`program_department.api.manage`. Dos bloques en la misma pantalla: el mapeo de
cada carrera a su departamento académico (con el nombre oficial que usa el
oficio) y los ajustes del oficio por departamento (encabezado, destinatario y
«Atn.»). La lógica vive en `ProgramDepartmentService`; aquí solo se arma el
contexto y se traducen los errores (400 + `X-Tt-Error`, éxito = parcial
re-pintado + `X-Tt-Notice`).

Con el corte a T-soft en la fase 4 o antes (R-G, `ProgramDepartmentService.operable`)
la pantalla es un estado vacío informativo y las acciones responden 400.
Ninguna ruta lleva `{process_id}`: no hay alcance por carrera que guardar.
"""
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from itcj2.apps.titulatec.pages.nav import render_titulatec
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.titulatec.pages.carreras_admin")
router = APIRouter(prefix="/admin/carreras-deptos", tags=["titulatec-pages-carreras"])

_VIEW_PERMS = ["titulatec.program_department.page.list"]
_MANAGE_PERMS = ["titulatec.program_department.api.manage"]

_PAGE_TPL = "titulatec/admin/carreras.html"
_BODY_TPL = "titulatec/partials/carreras/_body.html"


def _hdr(msg: str) -> str:
    """Percent-encode para que un mensaje acentuado quepa en un header latin-1
    (`titulatec-utils.js::decodeHeaderMsg` lo deshace al mostrarlo)."""
    return quote(msg or "", safe="")


def _to_int(raw):
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _body_ctx(db, user_id: int) -> dict:
    from itcj2.apps.titulatec.services.program_department_service import ProgramDepartmentService
    from itcj2.core.services.authz_cache import cached_perms

    operable = ProgramDepartmentService.operable(db)
    can_manage = set(_MANAGE_PERMS) <= set(cached_perms(db, user_id, "titulatec"))
    ctx = {"operable": operable, "can_manage": can_manage,
           "mapping": [], "departments": [], "settings": []}
    if operable:
        ctx["mapping"] = ProgramDepartmentService.list_mapping(db)
        ctx["departments"] = ProgramDepartmentService.academic_departments_catalog(db)
        ctx["settings"] = ProgramDepartmentService.list_settings(db)
    return ctx


def _repintar(request, db, user_id: int, aviso: str):
    resp = render_titulatec(request, _BODY_TPL, _body_ctx(db, user_id))
    resp.headers["X-Tt-Notice"] = _hdr(aviso)
    resp.headers["X-Tt-Notice-Kind"] = "success"
    return resp


def _error(msg: str):
    return Response(status_code=400, headers={"X-Tt-Error": _hdr(msg)})


# ===========================================================================
# Páginas
# ===========================================================================
@router.get("", name="titulatec.pages.carreras.home")
def home(request: Request,
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, int(user["sub"]))
    finally:
        db.close()
    return render_titulatec(request, _PAGE_TPL, ctx)


# ===========================================================================
# Acciones
# ===========================================================================
@router.post("/programa/{program_id}", name="titulatec.pages.carreras.set_department")
async def set_department(program_id: int, request: Request,
                         user: dict = Depends(require_page_app("titulatec", perms=_MANAGE_PERMS))):
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_set_department, program_id=program_id, request=request, user=user, form=form)


def _cuerpo_set_department(program_id, request, user, form):
    """Cuerpo síncrono de `set_department`: corre en el threadpool."""
    from itcj2.apps.titulatec.services.program_department_service import ProgramDepartmentService
    from itcj2.database import SessionLocal

    uid = int(user["sub"])
    department_id = _to_int(form.get("department_id"))
    if department_id is None:
        return _error("Elige un departamento.")
    db = SessionLocal()
    try:
        try:
            changed = ProgramDepartmentService.set_department(
                db, uid, program_id, department_id, form.get("official_name"))
        except ValueError as exc:
            # El servicio valida ANTES de escribir: no hay nada que deshacer.
            return _error(str(exc))
        return _repintar(request, db, uid,
                         "Carrera actualizada." if changed else "Sin cambios.")
    finally:
        db.close()


@router.post("/depto/{department_id}", name="titulatec.pages.carreras.update_settings")
async def update_settings(department_id: int, request: Request,
                          user: dict = Depends(require_page_app("titulatec", perms=_MANAGE_PERMS))):
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_update_settings, department_id=department_id, request=request, user=user, form=form)


def _cuerpo_update_settings(department_id, request, user, form):
    """Cuerpo síncrono de `update_settings`: corre en el threadpool."""
    from itcj2.apps.titulatec.services.program_department_service import ProgramDepartmentService
    from itcj2.database import SessionLocal

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        try:
            changed = ProgramDepartmentService.update_settings(
                db, uid, department_id,
                oficio_header=form.get("oficio_header"),
                addressee_position_code=form.get("addressee_position_code"),
                attn_position_code=form.get("attn_position_code"))
        except ValueError as exc:
            # El servicio valida ANTES de escribir: no hay nada que deshacer.
            return _error(str(exc))
        return _repintar(request, db, uid,
                         "Ajustes del oficio guardados." if changed else "Sin cambios.")
    finally:
        db.close()
