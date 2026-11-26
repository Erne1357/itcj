"""Bandeja «Promedios» (spec 2026-11-26-titulatec-promedios-pendientes-design.md §6-§7).

Expedientes sin promedio oficial, capturados a mano o por archivo. Dos vistas que
resuelve `AverageQueueService.view_for` (la misma fuente que el gate):

- CC (Centro de Cómputo y `admin`, con `titulatec.average.api.request`): todo
  expediente, pestañas «Por capturar» y «Con Escolares».
- SE (Servicios Escolares): solo lo que CC pasó y de sus carreras; sin pestañas.

Cada ruta lleva EXACTAMENTE un código en `perms=[...]`: la lista es OR
(`itcj2/dependencies.py`), así que un código de más abre la acción entera.
Todas devuelven el parcial completo `#tt-avg-body` (`outerHTML`); un error de
valor es 400 + `X-Tt-Error` (HTMX no hace swap en 4xx: el toast lo muestra).
La sesión se cierra ANTES de renderizar: el contexto lleva valores planos.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from itcj2.apps.titulatec.pages.nav import render_titulatec
from itcj2.apps.titulatec.services.average_queue_service import (
    LOAD_BUCKETS,
    LOAD_LABELS,
    TABS,
    AverageQueueService,
)
from itcj2.apps.titulatec.utils.paging import PAGE_SIZE, normalize_q, parse_page
from itcj2.apps.titulatec.utils.two_columns import leer_dos_columnas
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.titulatec.pages.averages_admin")
router = APIRouter(prefix="/admin/promedios", tags=["titulatec-pages-averages"])
# Las rutas con `{process_id}` NO usan `assert_process_in_scope` (alcance de
# encargado, dejaría fuera a CC): su guarda es la bandeja, `_lock_in_tray` dentro
# de cada mutador del servicio (404 si no está en la bandeja del actor). Están
# declaradas como excepción en el censo de `test_scope_guard.py`.

_LIST = ["titulatec.average.page.list"]
_CAPTURE = ["titulatec.average.api.capture"]
_REQUEST = ["titulatec.average.api.request"]

_BODY = "titulatec/admin/partials/averages_body.html"
_MAX_FILE_BYTES = 1024 * 1024
# Mismos alias que la CLI (`cli/titulatec/promedios.py::_PROMEDIOS_ALIAS`); se
# duplica para no importar un módulo de CLI desde una página.
_PROMEDIOS_ALIAS = {"promedio", "promedio_final", "promedio_oficial", "promedio_general"}
_MSG_NO_FILE = "Elige un archivo CSV o TXT con las columnas «control» y «promedio»."
_MSG_BIG_FILE = "El archivo pesa más de 1 MB: divídelo en partes."
_MSG_EMPTY_FILE = "El archivo no trae filas con datos."


def _hdr(msg: str) -> str:
    """Percent-encode para que un mensaje acentuado quepa en un header latin-1
    (`titulatec-utils.js::decodeHeaderMsg` lo deshace)."""
    return quote(msg or "", safe="")


def _error(msg: str) -> Response:
    return Response(status_code=400, headers={"X-Tt-Error": _hdr(msg)})


def _with_notice(resp, msg: str, kind: str = "success"):
    resp.headers["X-Tt-Notice"] = _hdr(msg)
    resp.headers["X-Tt-Notice-Kind"] = kind
    return resp


def _fmt(dt) -> str:
    return dt.strftime("%d/%m/%Y") if dt else ""


def _body_ctx(db, *, user_id: int, tab, q=None, page=1, result=None,
              per_page: int = PAGE_SIZE) -> dict:
    """Contexto del parcial. Alcance vacío de SE: aviso `no_programs` (fail-closed,
    sin consultar), distinto de «sin resultados con este filtro»."""
    view, allowed = AverageQueueService.view_for(db, user_id)
    is_cc = view == "cc"
    tab = tab if is_cc and tab in TABS else ("pending" if is_cc else "requested")
    # «» y no None: la plantilla lo pinta en el buscador y en los campos ocultos,
    # y un «None» literal volvería como búsqueda en el siguiente POST.
    q = normalize_q(q) or ""
    ctx = {
        "view": view, "is_cc": is_cc, "tab": tab, "q": q, "result": result,
        "no_programs": False, "rows": [], "page": None,
        "tabs": (("pending", "Por capturar"), ("requested", "Con Escolares")),
        "tab_counts": {"pending": 0, "requested": 0},
    }
    if allowed != "ALL" and not allowed:
        ctx["no_programs"] = True
        return ctx
    ctx["tab_counts"] = AverageQueueService.tab_counts(
        db, view=view, allowed_program_ids=allowed, q=q or None)
    pg = AverageQueueService.tray(db, view=view, tab=tab, allowed_program_ids=allowed,
                                  q=q or None, page=parse_page(page), per_page=per_page)
    ctx["page"] = pg
    ctx["rows"] = [{**vars(r), "requested_on": _fmt(r.requested_at)} for r in pg.items]
    return ctx


def _render_body(request: Request, db, user_id: int, form, result=None):
    """Re-pinta la MISMA pestaña, búsqueda y página del formulario."""
    ctx = _body_ctx(db, user_id=user_id, tab=form.get("tab"), q=form.get("q"),
                    page=form.get("page"), result=result)
    return render_titulatec(request, _BODY, ctx)


@router.get("", name="titulatec.pages.averages.list")
def list_averages(request: Request, tab: str = "", q: str = "", page: str = "",
                  user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), tab=tab, q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/averages.html", ctx)


@router.get("/body", name="titulatec.pages.averages.body")
def body(request: Request, tab: str = "", q: str = "", page: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    """Hermana de la página: acepta LOS MISMOS query params."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), tab=tab, q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, _BODY, ctx)


@router.post("/archivo", name="titulatec.pages.averages.upload")
async def upload(request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_CAPTURE))):
    """Carga por archivo (`control` + `promedio`) sobre la bandeja del actor."""
    form = await request.form()
    return await run_in_threadpool(_cuerpo_upload, request=request, user=user, form=form)


def _decode(raw: bytes) -> str:
    """UTF-16 con BOM («Texto Unicode» de Excel), UTF-8 (con o sin BOM) o, si no,
    latin-1 (los CSV de Excel en español suelen venir así)."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _cuerpo_upload(request, user, form):
    """Cuerpo síncrono de `upload`: corre en el threadpool, no en el event loop.
    El formulario ya está en un archivo temporal: leerlo aquí no bloquea el loop."""
    from itcj2.database import SessionLocal

    archivo = form.get("archivo")
    if archivo is None or not hasattr(archivo, "file"):
        return _error(_MSG_NO_FILE)
    raw = archivo.file.read(_MAX_FILE_BYTES + 1)
    if len(raw) > _MAX_FILE_BYTES:
        return _error(_MSG_BIG_FILE)
    nombre = archivo.filename or ""
    try:
        filas = leer_dos_columnas(_decode(raw), "promedio", _PROMEDIOS_ALIAS, estricto=True)
    except ValueError as exc:
        return _error(str(exc))
    if not filas:
        return _error(_MSG_EMPTY_FILE)

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        view, allowed = AverageQueueService.view_for(db, uid)
        res = AverageQueueService.load_rows(
            db, filas, actor_id=uid, view=view, allowed_program_ids=allowed)
        result = {
            "filename": nombre, "total": len(filas),
            "groups": [{"key": b, "label": LOAD_LABELS[b], "items": res[b]}
                       for b in LOAD_BUCKETS],
        }
        applied = len(res["applied"])
        resp = _render_body(request, db, uid, form, result=result)
    finally:
        db.close()
    return _with_notice(
        resp, f"{applied} de {len(filas)} fila(s) aplicadas.",
        "success" if applied else "warning")


@router.post("/{process_id}/guardar", name="titulatec.pages.averages.save")
async def save(process_id: int, request: Request,
               user: dict = Depends(require_page_app("titulatec", perms=_CAPTURE))):
    form = await request.form()
    return await run_in_threadpool(
        _cuerpo_save, process_id=process_id, request=request, user=user, form=form)


def _cuerpo_save(process_id, request, user, form):
    """Cuerpo síncrono de `save`: corre en el threadpool, no en el event loop."""
    from itcj2.apps.titulatec.models import TitulationProcess as TP
    from itcj2.core.models.user import User
    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        view, allowed = AverageQueueService.view_for(db, uid)
        try:
            valor = AverageQueueService.capture(
                db, process_id, form.get("promedio"), actor_id=uid, view=view,
                allowed_program_ids=allowed)
        except LookupError:
            return Response(status_code=404)
        except ValueError as exc:
            return _error(str(exc))
        # Después de `capture`: solo se lee un expediente que ya pasó la bandeja.
        control = (db.query(User.control_number).join(TP, TP.student_id == User.id)
                   .filter(TP.id == process_id).scalar())
        resp = _render_body(request, db, uid, form)
    finally:
        db.close()
    return _with_notice(resp, f"Promedio {valor:.2f} guardado · {control}")


@router.post("/{process_id}/pasar-a-escolares", name="titulatec.pages.averages.request")
async def request_school_services(
        process_id: int, request: Request,
        user: dict = Depends(require_page_app("titulatec", perms=_REQUEST))):
    form = await request.form()
    return await run_in_threadpool(
        _cuerpo_move, process_id=process_id, request=request, user=user, form=form,
        accion=AverageQueueService.request_school_services)


@router.post("/{process_id}/regresar", name="titulatec.pages.averages.withdraw")
async def withdraw(process_id: int, request: Request,
                   user: dict = Depends(require_page_app("titulatec", perms=_REQUEST))):
    form = await request.form()
    return await run_in_threadpool(
        _cuerpo_move, process_id=process_id, request=request, user=user, form=form,
        accion=AverageQueueService.withdraw_request)


def _cuerpo_move(process_id, request, user, form, accion):
    """Cuerpo síncrono de pasar/regresar: corre en el threadpool."""
    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        uid = int(user["sub"])
        try:
            accion(db, process_id, actor_id=uid)
        except LookupError:
            return Response(status_code=404)
        except ValueError as exc:
            return _error(str(exc))
        return _render_body(request, db, uid, form)
    finally:
        db.close()
