"""Vista «Anexo III» de la pestaña Titulación (fase 6, spec 2026-10-22 §9.2, D3).

Hermana de la vista «Formato B» (`pages/titulacion_admin.py`, mismo molde):
bandeja FIFO master-detail del escaneo firmado del Anexo III, visor del
escaneo, Aprobar / Observar (con motivo) y «quién lo está revisando». El
dictamen vive en `AnexoService` (puerta única de la fase 6), la bandeja en
`AnexoInboxService` y la presencia en `ReviewPresence`.

Acceso: la página exige `titulacion.page.list`; la vista (el parcial y toda
ruta con `{process_id}`) exige ADEMÁS `anexo_iii.api.review`
(`_exigir_bandeja`, después de `assert_process_in_scope`). Con el Anexo no
operable (corte a T-soft en la fase 6 o antes) la vista es un estado vacío y
las acciones responden 400: la liga «Anexo III» ni aparece (`views_ctx`).

Se registra en `pages/router.py` ANTES que `titulacion_admin`, para que ninguna
ruta de ese prefijo pueda capturar `anexo`.
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.titulacion_anexo")
router = APIRouter(prefix="/admin/titulacion/anexo", tags=["titulatec-pages-titulacion-anexo"])

_VIEW_PERMS = ["titulatec.titulacion.page.list"]
_REVIEW_PERM = "titulatec.anexo_iii.api.review"

_BASE_URL = "/titulatec/admin/titulacion/anexo"
_PAGE_TPL = "titulatec/admin/titulacion.html"
_BODY_TPL = "titulatec/partials/titulacion_anexo/_body.html"

# Tipo de revisión en `ReviewPresence` (la clave de Redis lo lleva).
_PRESENCE_KIND = "anexo_iii"
_NEXT_TRIES = 10

_TABS = (("pending", "Por revisar"), ("observed", "Con observaciones"),
         ("approved", "Aprobados"), ("unsent", "Sin enviar"))
_TAB_BY_PHASE_STATUS = {"in_review": "pending", "rejected": "observed", "approved": "approved"}

VERSION_CHANGED_NOTICE = "El alumno subió otro escaneo; revísalo de nuevo."
_VACIO = "—"


def _hdr(msg: str) -> str:
    """Percent-encode para que un mensaje acentuado quepa en un header latin-1."""
    from urllib.parse import quote
    return quote(msg or "", safe="")


def _to_int(raw):
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _puede_ver_anexo(perms) -> bool:
    """Abrir la pestaña Y revisar el Anexo III (los dos)."""
    return set(_VIEW_PERMS) <= set(perms) and _REVIEW_PERM in perms


def _exigir_bandeja(db, user_id: int) -> None:
    """Toda ruta de la vista exige poder ABRIRLA. 403 como el gate, ANTES de
    escribir; va después de `assert_process_in_scope` (`test_scope_guard.py`)."""
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.exceptions import PageForbidden

    if not _puede_ver_anexo(cached_perms(db, user_id, "titulatec")):
        raise PageForbidden(has_app_access=True)


def _operable(db) -> bool:
    from itcj2.apps.titulatec.services.anexo_service import AnexoService
    return AnexoService.operable(db)


def views_ctx(db, perms) -> dict:
    """Lo que la página de Titulación necesita para pintar sus vistas hermanas."""
    return {"anexo_operable": bool(_operable(db)),
            "can_review_anexo": _puede_ver_anexo(perms)}


def _nombre(user) -> str:
    return " ".join(p for p in (user.first_name, user.last_name) if p) if user else ""


def _viewer_name(db, user_id: int) -> str:
    from itcj2.core.models.user import User
    return _nombre(db.get(User, user_id)) or "Otra persona"


def _infer_tab(db, user_id: int, process_id: int) -> str:
    """Pestaña de un `?selected=` sin ella; solo mira procesos en alcance."""
    from itcj2.apps.titulatec.models import ProcessPhase
    from itcj2.apps.titulatec.services.anexo_service import AnexoService
    from itcj2.apps.titulatec.services.scope_service import process_in_scope

    if process_in_scope(db, user_id, process_id) is None:
        return "pending"
    n = AnexoService.phase_number(db)
    estado = (db.query(ProcessPhase.status)
              .filter(ProcessPhase.process_id == process_id,
                      ProcessPhase.phase_number == n).scalar()) if n is not None else None
    return _TAB_BY_PHASE_STATUS.get(estado, "unsent")


def _next_free(db, user_id: int, done_id: int, vista: dict | None = None):
    """El siguiente «Por revisar» de la cola FIFO que nadie más tenga abierto."""
    from itcj2.apps.titulatec.services.anexo_inbox_service import AnexoInboxService
    from itcj2.apps.titulatec.services.review_presence import ReviewPresence

    vista = vista or {}
    q, carrera = vista.get("q") or "", _to_int(vista.get("carrera"))
    excluir = {done_id}
    for _ in range(_NEXT_TRIES):
        pid = AnexoInboxService.next_pending(
            db, user_id, exclude_ids=excluir, q=q, program_id=carrera)
        if pid is None:
            return None
        if not ReviewPresence.viewers(_PRESENCE_KIND, [pid], exclude_user_id=user_id):
            return pid
        excluir.add(pid)
    return None


def _programs(db, user_id: int) -> list[dict]:
    from itcj2.apps.titulatec.services.scope_service import officer_programs
    from itcj2.core.models.program import Program

    scope = officer_programs(db, user_id)
    if scope != "ALL" and not scope:
        return []
    query = db.query(Program.id, Program.name).order_by(Program.name, Program.id)
    if scope != "ALL":
        query = query.filter(Program.id.in_(scope))
    return [{"id": p.id, "name": p.name} for p in query.all()]


def _detail_ctx(db, *, process_id: int, perms, operable: bool, others,
                error: str | None = None, reason: str = "") -> dict:
    """El detalle de UN proceso (dict plano; la sesión se cierra antes de pintar)."""
    from itcj2.apps.titulatec.models import (
        Document, Modality, ProcessPhase, TitulationProcess,
    )
    from itcj2.apps.titulatec.pages.admin import _PROCESS_VIEW_PERMS
    from itcj2.apps.titulatec.services.anexo_service import DOC_TYPE, AnexoService
    from itcj2.apps.titulatec.services.synodal_service import SynodalService
    from itcj2.apps.titulatec.utils.dates_es import dia_mes_hora
    from itcj2.core.models.program import Program
    from itcj2.core.models.user import User

    proc = db.get(TitulationProcess, process_id)
    alumno = db.get(User, proc.student_id)
    programa = db.get(Program, proc.program_id) if proc.program_id else None
    modalidad = db.get(Modality, proc.modality_id) if proc.modality_id else None
    n = AnexoService.phase_number(db)
    fase = (db.query(ProcessPhase.status)
            .filter(ProcessPhase.process_id == process_id,
                    ProcessPhase.phase_number == n).scalar()) if n is not None else None
    doc = (db.query(Document).filter_by(process_id=process_id, type_code=DOC_TYPE).first())
    anexo = AnexoService.get(db, process_id)

    en_revision = (operable and proc.status == "active" and fase == "in_review"
                   and doc is not None and doc.review_status == "pending")
    try:
        firmas = AnexoService.signer_labels(proc)
    except ValueError:
        firmas = []
    sinodales = SynodalService.active_for_process(db, process_id)
    nombre = " ".join(p for p in (alumno.first_name, alumno.last_name, alumno.middle_name)
                      if p) if alumno else ""
    revisado = None
    if doc is not None and doc.review_status in ("approved", "rejected") and doc.updated_at:
        revisado = ("Aprobado" if doc.review_status == "approved" else "Observado") \
            + f" el {dia_mes_hora(doc.updated_at)}"
    return {
        "process_id": process_id, "folio": proc.folio, "status": fase or "pending",
        "name": nombre or _VACIO,
        "control": (alumno.control_number if alumno else None) or _VACIO,
        "program": programa.name if programa else _VACIO,
        "modality": modalidad.name if modalidad else _VACIO,
        "anexo_folio": anexo.folio if anexo else None,
        "released_label": dia_mes_hora(anexo.released_at) if anexo and anexo.released_at else None,
        "sent_label": dia_mes_hora(doc.updated_at) if doc is not None and doc.updated_at else None,
        "signers": firmas, "sinodales": sinodales,
        "scan": ({"version": doc.version, "mime": doc.mime_type or "application/pdf",
                  "status": doc.review_status, "note": doc.review_note,
                  "url": f"{_BASE_URL}/{process_id}/escaneo?v={doc.version}"}
                 if doc is not None else None),
        "pdf_url": f"{_BASE_URL}/{process_id}/anexo.pdf",
        "reviewed_label": revisado,
        "can_review": en_revision and _REVIEW_PERM in perms,
        "form_error": error, "form_reason": reason,
        "others": list(others or []),
        "beat": en_revision,
        "can_open_exp": bool(set(_PROCESS_VIEW_PERMS) & set(perms)),
        "phase_number": n,
    }


def _body_ctx(db, *, user_id: int, tab, q, carrera, page, selected_id,
              per_page: int | None = None, error: str | None = None,
              reason: str = "") -> dict:
    """Contexto del parcial `_body.html` (y de la página completa)."""
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.apps.titulatec.services.anexo_inbox_service import AnexoInboxService
    from itcj2.apps.titulatec.services.review_presence import ReviewPresence
    from itcj2.apps.titulatec.utils.dates_es import dia_mes_hora
    from itcj2.apps.titulatec.utils.paging import PAGE_SIZE, Page, normalize_q

    perms = cached_perms(db, user_id, "titulatec")
    operable = _operable(db)
    can_read = _puede_ver_anexo(perms)
    q = normalize_q(q) or ""
    carrera_id = _to_int(carrera)
    if tab not in AnexoInboxService.TABS:
        tab = _infer_tab(db, user_id, selected_id) if selected_id else "pending"

    ctx = {
        "operable": operable, "can_read": can_read, "tab": tab, "tabs": _TABS,
        "q": q, "carrera": carrera_id, "rows": [],
        "page": Page(items=[], total=0, page=1, per_page=per_page or PAGE_SIZE),
        "counts": {t: 0 for t in AnexoInboxService.TABS}, "programs": [],
        "detail": None, "selected_id": None,
    }
    if not (operable and can_read):
        return ctx

    data = AnexoInboxService.list(db, user_id, tab=tab, q=q, program_id=carrera_id,
                                  page=page, per_page=per_page)
    rows = data["rows"]
    ids = [r["process_id"] for r in rows]
    detail_id = None
    if selected_id and (selected_id in ids or AnexoInboxService.contains(
            db, user_id, selected_id, tab=tab, q=q, program_id=carrera_id)):
        detail_id = selected_id
    viewers = ReviewPresence.viewers(
        _PRESENCE_KIND, ids + ([detail_id] if detail_id and detail_id not in ids else []),
        exclude_user_id=user_id)
    for r in rows:
        r["viewers"] = viewers.get(r["process_id"], [])
        r["sent_label"] = dia_mes_hora(r["sent_at"]) if r["sent_at"] else None

    detail = None
    if detail_id:
        detail = _detail_ctx(db, process_id=detail_id, perms=perms, operable=operable,
                             others=viewers.get(detail_id), error=error, reason=reason)
        if detail["beat"]:
            ReviewPresence.touch(_PRESENCE_KIND, detail_id, user_id,
                                 _viewer_name(db, user_id))

    ctx.update({"rows": rows, "page": data["page"], "counts": data["counts"],
                "programs": _programs(db, user_id), "detail": detail,
                "selected_id": detail_id})
    return ctx


def _vista(form) -> dict:
    """Pestaña, búsqueda, carrera y página desde las que se actuó (CLAUDE.md §18, regla 3)."""
    return {"tab": form.get("tab") or "pending", "q": form.get("q") or "",
            "carrera": form.get("carrera") or "", "page": form.get("page") or ""}


def _repintar(request, db, user_id: int, vista: dict, selected_id, aviso: str, *,
              kind: str = "success", error: str | None = None, reason: str = ""):
    """Re-pinta el cuerpo con `selected_id`, el aviso (`X-Tt-Notice`) y, si lo hay,
    el error de validación del formulario del detalle."""
    ctx = _body_ctx(db, user_id=user_id, selected_id=selected_id, error=error,
                    reason=reason, **vista)
    resp = render_titulatec(request, _BODY_TPL, ctx)
    if aviso:
        resp.headers["X-Tt-Notice"] = _hdr(aviso)
        resp.headers["X-Tt-Notice-Kind"] = kind
    return resp


def _bloqueo_por_corte():
    from itcj2.apps.titulatec.services.anexo_service import NOT_OPERABLE_MSG
    return Response(status_code=400, headers={"X-Tt-Error": _hdr(NOT_OPERABLE_MSG)})


# ===========================================================================
# Páginas
# ===========================================================================
@router.get("", name="titulatec.pages.titulacion_anexo.home")
def home(request: Request, tab: str = "", q: str = "", carrera: str = "", page: str = "",
         selected: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    """Página completa de la vista «Anexo III»."""
    from itcj2.database import SessionLocal
    from itcj2.core.services.authz_cache import cached_perms

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=uid, tab=tab, q=q, carrera=carrera, page=page,
                        selected_id=_to_int(selected))
        ctx.update(views_ctx(db, cached_perms(db, uid, "titulatec")))
    finally:
        db.close()
    ctx.update(view="anexo", body_tpl=_BODY_TPL)
    return render_titulatec(request, _PAGE_TPL, ctx)


@router.get("/body", name="titulatec.pages.titulacion_anexo.body")
def body(request: Request, tab: str = "", q: str = "", carrera: str = "", page: str = "",
         selected: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    """Parcial `#tt-tit-body` de la vista: pestañas, búsqueda, carrera, página y detalle."""
    from itcj2.database import SessionLocal
    uid = int(user["sub"])
    db = SessionLocal()
    try:
        _exigir_bandeja(db, uid)
        ctx = _body_ctx(db, user_id=uid, tab=tab, q=q, carrera=carrera, page=page,
                        selected_id=_to_int(selected))
    finally:
        db.close()
    return render_titulatec(request, _BODY_TPL, ctx)


# ===========================================================================
# Dictamen
# ===========================================================================
@router.post("/{process_id}/aprobar", name="titulatec.pages.titulacion_anexo.approve")
async def approve(process_id: int, request: Request,
                  user: dict = Depends(require_page_app("titulatec", perms=[_REVIEW_PERM]))):
    """Aprueba el escaneo y, en la misma transacción, la fase 6."""
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_approve, process_id=process_id, request=request, user=user, form=form)


def _cuerpo_approve(process_id, request, user, form):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.anexo_service import AnexoService, AnexoVersionChanged
    from itcj2.apps.titulatec.services.review_presence import ReviewPresence
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, uid, process_id)
        _exigir_bandeja(db, uid)
        if not _operable(db):
            return _bloqueo_por_corte()
        version = _to_int(form.get("version"))
        if version is None:
            return _repintar(request, db, uid, _vista(form), process_id,
                             VERSION_CHANGED_NOTICE, kind="warning")
        try:
            AnexoService.approve(db, proc, uid, expected_version=version)
        except AnexoVersionChanged:
            db.commit()
            return _repintar(request, db, uid, _vista(form), process_id,
                             VERSION_CHANGED_NOTICE, kind="warning")
        except ValueError as exc:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        ReviewPresence.clear(_PRESENCE_KIND, process_id, uid)
        siguiente = _next_free(db, uid, process_id, _vista(form))
        return _repintar(request, db, uid, _vista(form), siguiente,
                         "Anexo III aprobado: el proceso pasó a la siguiente fase.")
    finally:
        db.close()


@router.post("/{process_id}/observar", name="titulatec.pages.titulacion_anexo.observe")
async def observe(process_id: int, request: Request,
                  user: dict = Depends(require_page_app("titulatec", perms=[_REVIEW_PERM]))):
    """Regresa el escaneo al alumno con un motivo obligatorio (`reason`)."""
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_observe, process_id=process_id, request=request, user=user, form=form)


def _cuerpo_observe(process_id, request, user, form):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.anexo_service import (
        REASON_REQUIRED_MSG, REASON_TOO_LONG_MSG, AnexoService, AnexoVersionChanged,
    )
    from itcj2.apps.titulatec.services.review_presence import ReviewPresence
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    motivo = form.get("reason") or ""
    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, uid, process_id)
        _exigir_bandeja(db, uid)
        if not _operable(db):
            return _bloqueo_por_corte()
        version = _to_int(form.get("version"))
        if version is None:
            return _repintar(request, db, uid, _vista(form), process_id,
                             VERSION_CHANGED_NOTICE, kind="warning")
        try:
            AnexoService.observe(db, proc, uid, reason=motivo, expected_version=version)
        except AnexoVersionChanged:
            db.commit()
            return _repintar(request, db, uid, _vista(form), process_id,
                             VERSION_CHANGED_NOTICE, kind="warning")
        except ValueError as exc:
            if str(exc) in (REASON_REQUIRED_MSG, REASON_TOO_LONG_MSG):
                # Error de validación: 200 con el formulario re-pintado (htmx no
                # hace swap en un 4xx) y el motivo tecleado conservado.
                return _repintar(request, db, uid, _vista(form), process_id, "",
                                 error=str(exc), reason=motivo)
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        ReviewPresence.clear(_PRESENCE_KIND, process_id, uid)
        siguiente = _next_free(db, uid, process_id, _vista(form))
        return _repintar(request, db, uid, _vista(form), siguiente,
                         "Anexo III regresado al alumno con observaciones.")
    finally:
        db.close()


# ===========================================================================
# Presencia, escaneo y Anexo generado
# ===========================================================================
@router.post("/{process_id}/viendo", name="titulatec.pages.titulacion_anexo.viewing")
def viewing(process_id: int, request: Request,
            user: dict = Depends(require_page_app("titulatec", perms=[_REVIEW_PERM]))):
    """Latido de presencia (cada 60 s desde el detalle abierto) → 204."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.review_presence import ReviewPresence
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        assert_process_in_scope(db, uid, process_id)
        _exigir_bandeja(db, uid)
        if _operable(db):
            ReviewPresence.touch(_PRESENCE_KIND, process_id, uid, _viewer_name(db, uid))
    finally:
        db.close()
    return Response(status_code=204)


@router.get("/{process_id}/escaneo", name="titulatec.pages.titulacion_anexo.scan")
def scan_file(process_id: int, request: Request,
              user: dict = Depends(require_page_app("titulatec", perms=[_REVIEW_PERM]))):
    """Sirve INLINE el escaneo firmado del Anexo III del proceso."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.anexo_service import DOC_TYPE
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope
    from itcj2.apps.titulatec.utils import storage

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, uid, process_id)
        _exigir_bandeja(db, uid)
        if not _operable(db):
            return Response(status_code=404)
        doc = DocumentService.get_document(db, process_id, DOC_TYPE)
        if not doc:
            return Response(status_code=404)
        path = storage.abs_path(doc.file_path)
        mime = doc.mime_type
        _period, control = DocumentService._storage_keys(db, proc)
        filename = storage.download_filename(control, DOC_TYPE, doc.file_path)
    finally:
        db.close()
    if not path.exists():
        return Response(status_code=404)
    return FileResponse(str(path), media_type=mime,
                        headers={"Content-Disposition": f'inline; filename="{filename}"',
                                 "X-Content-Type-Options": "nosniff"})


@router.get("/{process_id}/anexo.pdf", name="titulatec.pages.titulacion_anexo.pdf")
def anexo_pdf(process_id: int, request: Request,
              user: dict = Depends(require_page_app("titulatec", perms=[_REVIEW_PERM]))):
    """El Anexo III generado (PDF inline). Emite el folio si todavía no lo tiene."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.anexo_service import AnexoService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, uid, process_id)
        _exigir_bandeja(db, uid)
        if not _operable(db):
            return Response(status_code=404)
        try:
            pdf = AnexoService.render_pdf(db, proc, uid)
            db.commit()
        except ValueError as exc:
            db.rollback()
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        nombre = AnexoService.filename(db, proc)
    finally:
        db.close()
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{nombre}"',
                             "X-Content-Type-Options": "nosniff"})
