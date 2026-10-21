"""Pestaña «Titulación»: la pantalla de trabajo del Departamento de Titulación.

Spec `docs/superpowers/specs/2026-10-21-titulatec-fase3-formato-b-titulacion-design.md`
§8. Hoy hospeda una sola vista, el Formato B (fase 3): bandeja FIFO
master-detail (mismo patrón que `pages/documents.py`), observaciones por campo,
aprobar, corregir los datos del registro (§8.5), visor de los documentos de la
fase 1 y la presencia «quién lo está revisando» (§8.3).

Reparto: el dictamen vive en `FormatBService`, la bandeja en
`FormatBInboxService` y la presencia en `ReviewPresence` (Redis, cosmética y
fail-open). Aquí solo se arma el contexto y se traducen los errores.

Acceso (§8.1, §8.4): la página exige `titulacion.page.list`; la vista del
Formato B (el parcial y toda ruta con `{process_id}`) exige ADEMÁS
`format_b.api.read.all` (`_exigir_bandeja`). Cada ruta con `{process_id}` llama
a `assert_process_in_scope` como primera sentencia del `try` y luego a
`_exigir_bandeja` -- no a `_exigir_vista_completa` de Procesos: el Depto. no
abre Procesos (corrige P6). Con el corte a T-soft en la fase del Formato B o
antes (`_operable`), la pestaña es un estado vacío informativo y las acciones
responden 400 (en producción el corte es 3).
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.titulacion_admin")
router = APIRouter(prefix="/admin/titulacion", tags=["titulatec-pages-titulacion"])

# Abrir la pestaña (y el ítem del menú, `nav._ADMIN_NAV`).
_VIEW_PERMS = ["titulatec.titulacion.page.list"]
# Ver el Formato B; con `_VIEW_PERMS` forma la guarda de bandeja.
_READ_PERM = "titulatec.format_b.api.read.all"
_APPROVE_PERM = "titulatec.format_b.api.approve"
_REJECT_PERM = "titulatec.format_b.api.reject"
_CORRECT_PERM = "titulatec.format_b.api.correct_registry"

_BASE_URL = "/titulatec/admin/titulacion"
_PAGE_TPL = "titulatec/admin/titulacion.html"
_BODY_TPL = "titulatec/partials/titulacion/_body.html"

# Tipo de revisión en `ReviewPresence` (la clave de Redis lo lleva).
_PRESENCE_KIND = "format_b"
# Al elegir el siguiente de la cola tras dictaminar se saltan, a lo más, estos
# procesos abiertos por otra persona (el Depto. son dos o tres revisores).
_NEXT_TRIES = 10

# Pestañas en el orden de pantalla (las claves son `FormatBInboxService.TABS`).
_TABS = (("pending", "Por revisar"), ("observed", "Con observaciones"),
         ("approved", "Aprobados"), ("unsent", "Sin enviar"))
# `?selected=` sin pestaña (la liga «Abrir en Titulación» del expediente): la
# pestaña sale del estado del Formato B; sin enviar o sin Formato B, «Sin enviar».
_TAB_BY_STATUS = {"submitted": "pending", "rejected": "observed", "approved": "approved"}

# Cada campo observado llega como `note__{campo}` (una caja por campo editable).
_NOTE_PREFIX = "note__"
# El «vacío» con que `display_sections` pinta un dato sin valor.
_VACIO = "—"


def _hdr(msg: str) -> str:
    """Percent-encode para que un mensaje acentuado quepa en un header latin-1.

    Gemelo de `pages/documents.py::_hdr`; `titulatec-utils.js::decodeHeaderMsg`
    lo deshace al mostrarlo.
    """
    from urllib.parse import quote
    return quote(msg or "", safe="")


def _to_int(raw):
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _puede_ver(perms) -> bool:
    """Abrir la pestaña Y leer el Formato B (los dos, no uno u otro)."""
    return set(_VIEW_PERMS) <= set(perms) and _READ_PERM in perms


def _exigir_bandeja(db, user_id: int) -> None:
    """Las rutas del Formato B exigen poder ABRIR esta vista, no solo el permiso
    de la acción: el dictamen de `format_b.api.*` existía antes que la pestaña
    (patrón `documents.py::_exigir_bandeja`). 403 como el gate, ANTES de
    escribir. Va después de `assert_process_in_scope` (`test_scope_guard.py`)."""
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.exceptions import PageForbidden

    if not _puede_ver(cached_perms(db, user_id, "titulatec")):
        raise PageForbidden(has_app_access=True)


def _fase_formato_b(db):
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    return PhaseService.phase_number_for_code(db, "format_b")


def _operable(db) -> bool:
    """¿La fase del Formato B se opera en esta app? Falla cerrado: sin la fase
    en el catálogo, o con el corte a T-soft en ella o antes, no."""
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    n = _fase_formato_b(db)
    return n is not None and PhaseService._handoff_phase() > n


def _nombre(user) -> str:
    return " ".join(p for p in (user.first_name, user.last_name) if p) if user else ""


def _viewer_name(db, user_id: int) -> str:
    """Nombre con que el revisor aparece en la insignia de los demás."""
    from itcj2.core.models.user import User
    return _nombre(db.get(User, user_id)) or "Otra persona"


def _infer_tab(db, user_id: int, process_id: int) -> str:
    """Pestaña de un `?selected=` que llega sin ella. Solo mira procesos en
    alcance: la pestaña marcada no debe delatar el estado de uno ajeno."""
    from itcj2.apps.titulatec.models import FormatB
    from itcj2.apps.titulatec.services.scope_service import process_in_scope

    if process_in_scope(db, user_id, process_id) is None:
        return "pending"
    fb = db.get(FormatB, process_id)
    return _TAB_BY_STATUS.get(getattr(fb, "status", None), "unsent")


def _en_universo(db, user_id: int, process_id: int, *, tab: str, q, carrera) -> bool:
    """¿`process_id` está en la pestaña, búsqueda, carrera y alcance vigentes?

    `?selected=` se resuelve DENTRO de las filas ya acotadas (patrón Documentos),
    también cuando el proceso cae en otra página: el mismo `_base` y el mismo
    predicado de pestaña que la lista, más el id. Una consulta.
    """
    from itcj2.apps.titulatec.services.format_b_inbox_service import FormatBInboxService

    return FormatBInboxService.contains(db, user_id, process_id, tab=tab, q=q or "",
                                        program_id=carrera)


def _next_free(db, user_id: int, done_id: int, vista: dict | None = None):
    """El siguiente «Por revisar» de la cola FIFO que nadie más tenga abierto.

    Salta el recién dictaminado y, uno por uno, los que otra persona tiene
    abiertos (§8.2); con Redis caído `viewers` devuelve vacío y gana la cabeza
    de la cola. Respeta la búsqueda y la carrera de la vista (`vista`): el
    siguiente es del conjunto FILTRADO. None si no queda ninguno libre.
    """
    from itcj2.apps.titulatec.services.format_b_inbox_service import FormatBInboxService
    from itcj2.apps.titulatec.services.review_presence import ReviewPresence

    vista = vista or {}
    q, carrera = vista.get("q") or "", _to_int(vista.get("carrera"))
    excluir = {done_id}
    for _ in range(_NEXT_TRIES):
        pid = FormatBInboxService.next_pending(
            db, user_id, exclude_ids=excluir, q=q, program_id=carrera)
        if pid is None:
            return None
        if not ReviewPresence.viewers(_PRESENCE_KIND, [pid], exclude_user_id=user_id):
            return pid
        excluir.add(pid)
    return None


def _programs(db, user_id: int) -> list[dict]:
    """Carreras del filtro: las del alcance del usuario (todas con «ALL")."""
    from itcj2.apps.titulatec.services.scope_service import officer_programs
    from itcj2.core.models.program import Program

    scope = officer_programs(db, user_id)
    if scope != "ALL" and not scope:
        return []
    query = db.query(Program.id, Program.name).order_by(Program.name, Program.id)
    if scope != "ALL":
        query = query.filter(Program.id.in_(scope))
    return [{"id": p.id, "name": p.name} for p in query.all()]


def _detail_ctx(db, *, process_id: int, perms, operable: bool, others) -> dict:
    """El detalle de UN proceso: datos de pantalla, permisos de acción y docs.

    Todo lo que llega a la plantilla es un dict plano (la sesión se cierra antes
    de pintar la página completa).
    """
    from itcj2.apps.titulatec.models import Document, DocumentType, FormatB, TitulationProcess
    from itcj2.apps.titulatec.pages.admin import _PROCESS_VIEW_PERMS
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.format_b_service import NO_MODALITY_MSG, FormatBService
    from itcj2.apps.titulatec.services.track_service import TrackService
    from itcj2.apps.titulatec.utils.dates_es import dia_mes_hora
    from itcj2.core.models.user import User

    proc = db.get(TitulationProcess, process_id)
    fb = db.get(FormatB, process_id)
    status = getattr(fb, "status", None) or "draft"
    secciones = FormatBService.display_sections(db, fb, proc)
    valores = {r["field"]: r["value"] for s in secciones for r in s["rows"]}
    nombre = " ".join(valores[c] for c in ("first_name", "last_name", "middle_name")
                      if valores.get(c) not in (None, "", _VACIO))

    en_revision = operable and status == "submitted"
    # Aprobar exige el tipo de titulación elegido (`NO_MODALITY_MSG` del
    # service): uno enviado antes de esa columna solo se puede observar.
    sin_modalidad = en_revision and not getattr(fb, "modality_id", None)
    can_approve = en_revision and _APPROVE_PERM in perms and not sin_modalidad
    can_reject = en_revision and _REJECT_PERM in perms
    can_correct = en_revision and _CORRECT_PERM in perms

    # Observaciones vigentes: las ve el revisor de la ronda siguiente (con su
    # «antes → ahora») y quien abre uno que espera al alumno. Un aprobado las
    # conserva en la BD (§6), pero ya no dicen nada.
    obs = getattr(fb, "review_observations", None)
    show_obs = status in ("submitted", "rejected") and isinstance(obs, dict)
    general_prev = obs.get("general") if show_obs else None

    revisado = None
    if fb is not None and status in ("rejected", "approved") and fb.reviewed_at:
        quien = _nombre(db.get(User, fb.reviewed_by_id)) if fb.reviewed_by_id else ""
        revisado = ("Revisado" + (f" por {quien}" if quien else "")
                    + f" el {dia_mes_hora(fb.reviewed_at)}")

    # Documentos de la fase 1 que el alumno sí subió, en el orden de su perfil
    # (3 en licenciatura, 7 en posgrado): para cotejar el nombre con el acta y
    # la CURP. Dos consultas fijas.
    codigos = DocumentService.initial_doc_types_for(db, proc)
    presentes = {d.type_code: d for d in db.query(
        Document.type_code, Document.mime_type, Document.review_status)
        .filter(Document.process_id == process_id, Document.type_code.in_(codigos)).all()}
    nombres = (dict(db.query(DocumentType.code, DocumentType.name)
                    .filter(DocumentType.code.in_(list(presentes))).all())
               if presentes else {})
    docs = [{"type_code": c, "name": nombres.get(c, c),
             "mime": presentes[c].mime_type or "application/pdf",
             "status": presentes[c].review_status,
             "url": f"{_BASE_URL}/formato-b/{process_id}/documento/{c}"}
            for c in codigos if c in presentes]

    registro, carreras = {}, []
    if can_correct:
        registro = {"first_name": fb.first_name or "", "last_name": fb.last_name or "",
                    "middle_name": fb.middle_name or "", "program_id": proc.program_id}
        # Solo carreras del MISMO nivel (§8.5): el service lo vuelve a exigir.
        # El nivel solo lo lee `TrackService` (invariante 2 del posgrado).
        carreras = [{"id": p.id, "name": p.name}
                    for p in TrackService.programs_same_level(db, proc.program_id)]

    # R-E (spec fase 4 §16b): un Formato B aprobado muestra los sinodales
    # asignados y, con `synodal.api.read`, el oficio -- así `titulatec_titulacion`
    # lo ve sin necesitar el expediente completo.
    sinodales, can_oficio = [], False
    if status == "approved":
        from itcj2.apps.titulatec.services.synodal_service import SynodalService
        sinodales = SynodalService.active_for_process(db, process_id)
        can_oficio = bool(sinodales) and "titulatec.synodal.api.read" in perms

    return {
        "sinodales": sinodales, "can_oficio": can_oficio,
        "process_id": process_id, "folio": proc.folio, "status": status,
        "round": int(getattr(fb, "submission_count", 0) or 0),
        "name": nombre or _VACIO,
        "control": valores.get("control_number") or _VACIO,
        "program": valores.get("program_id") or _VACIO,
        "modality": valores.get("modality_id") or _VACIO,
        "submitted_label": (dia_mes_hora(fb.submitted_at)
                            if fb is not None and fb.submitted_at else None),
        "reviewed_label": revisado,
        "sections": secciones, "show_obs": show_obs, "general_prev": general_prev,
        "docs": docs,
        "can_approve": can_approve, "can_reject": can_reject, "can_correct": can_correct,
        "can_review": can_approve or can_reject,
        "no_modality_msg": NO_MODALITY_MSG if sin_modalidad else None,
        "registry": registro, "registry_programs": carreras,
        "others": list(others or []),
        # Latido de presencia: solo mientras se puede revisar (§8.3).
        "beat": en_revision,
        "can_open_exp": bool(set(_PROCESS_VIEW_PERMS) & set(perms)),
        "phase_number": _fase_formato_b(db),
    }


def _body_ctx(db, *, user_id: int, tab, q, carrera, page, selected_id,
              per_page: int | None = None) -> dict:
    """Contexto del parcial `_body.html` (y de la página completa).

    Pestaña desconocida o vacía: la del `?selected=` si lo hay, si no «Por
    revisar». Sin corte operable o sin lectura del Formato B, solo el estado
    vacío correspondiente (cero consultas de bandeja). Con detalle de un
    Formato B en revisión, marca la presencia del usuario (§8.3: «al abrir el
    detalle»).
    """
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.apps.titulatec.services.format_b_inbox_service import FormatBInboxService
    from itcj2.apps.titulatec.services.review_presence import ReviewPresence
    from itcj2.apps.titulatec.utils.dates_es import dia_mes_hora
    from itcj2.apps.titulatec.utils.paging import PAGE_SIZE, Page, normalize_q

    perms = cached_perms(db, user_id, "titulatec")
    operable = _operable(db)
    can_read = _puede_ver(perms)
    q = normalize_q(q) or ""
    carrera_id = _to_int(carrera)
    if tab not in FormatBInboxService.TABS:
        tab = _infer_tab(db, user_id, selected_id) if selected_id else "pending"

    ctx = {
        "operable": operable, "can_read": can_read, "tab": tab, "tabs": _TABS,
        "q": q, "carrera": carrera_id, "rows": [],
        "page": Page(items=[], total=0, page=1, per_page=per_page or PAGE_SIZE),
        "counts": {t: 0 for t in FormatBInboxService.TABS}, "programs": [],
        "detail": None, "selected_id": None,
    }
    if not (operable and can_read):
        return ctx

    data = FormatBInboxService.list(db, user_id, tab=tab, q=q, program_id=carrera_id,
                                    page=page, per_page=per_page)
    rows = data["rows"]
    ids = [r["process_id"] for r in rows]
    detail_id = None
    if selected_id and (selected_id in ids or _en_universo(
            db, user_id, selected_id, tab=tab, q=q, carrera=carrera_id)):
        detail_id = selected_id
    # Una sola ida a Redis para la página (y el detalle, si cae fuera de ella).
    viewers = ReviewPresence.viewers(
        _PRESENCE_KIND, ids + ([detail_id] if detail_id and detail_id not in ids else []),
        exclude_user_id=user_id)
    for r in rows:
        r["viewers"] = viewers.get(r["process_id"], [])
        r["submitted_label"] = dia_mes_hora(r["submitted_at"]) if r["submitted_at"] else None

    detail = None
    if detail_id:
        detail = _detail_ctx(db, process_id=detail_id, perms=perms, operable=operable,
                             others=viewers.get(detail_id))
        if detail["beat"]:
            ReviewPresence.touch(_PRESENCE_KIND, detail_id, user_id,
                                 _viewer_name(db, user_id))

    ctx.update({"rows": rows, "page": data["page"], "counts": data["counts"],
                "programs": _programs(db, user_id), "detail": detail,
                "selected_id": detail_id})
    return ctx


def _vista(form) -> dict:
    """La pestaña, búsqueda, carrera y página desde las que se actuó: la acción
    re-pinta la MISMA vista (regla 3 de la paginación, CLAUDE.md §18)."""
    return {"tab": form.get("tab") or "pending", "q": form.get("q") or "",
            "carrera": form.get("carrera") or "", "page": form.get("page") or ""}


def _repintar(request, db, user_id: int, vista: dict, selected_id, aviso: str):
    """Re-pinta el cuerpo con `selected_id` y el aviso de éxito (`X-Tt-Notice`)."""
    ctx = _body_ctx(db, user_id=user_id, selected_id=selected_id, **vista)
    resp = render_titulatec(request, _BODY_TPL, ctx)
    resp.headers["X-Tt-Notice"] = _hdr(aviso)
    resp.headers["X-Tt-Notice-Kind"] = "success"
    return resp


def _bloqueo_por_corte():
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    return Response(status_code=400, headers={"X-Tt-Error": _hdr(PhaseService.HANDOFF_MSG)})


# ===========================================================================
# Páginas
# ===========================================================================
@router.get("", name="titulatec.pages.titulacion.home")
def home(request: Request, tab: str = "", q: str = "", carrera: str = "", page: str = "",
         selected: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    """Página completa. Los parámetros llegan como `str` (htmx los manda
    vacíos) y se parsean a mano."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), tab=tab, q=q, carrera=carrera,
                        page=page, selected_id=_to_int(selected))
    finally:
        db.close()
    return render_titulatec(request, _PAGE_TPL, ctx)


@router.get("/body", name="titulatec.pages.titulacion.body")
def body(request: Request, tab: str = "", q: str = "", carrera: str = "", page: str = "",
         selected: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    """Parcial `#tt-tit-body`: pestañas, búsqueda, carrera, página y detalle."""
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
# Dictamen y corrección del registro
# ===========================================================================
@router.post("/formato-b/{process_id}/aprobar", name="titulatec.pages.titulacion.approve")
async def approve(process_id: int, request: Request,
                  user: dict = Depends(require_page_app("titulatec", perms=[_APPROVE_PERM]))):
    """Aprueba el Formato B y, en la misma transacción, la fase 3 (§7)."""
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_approve, process_id=process_id, request=request, user=user, form=form)


def _cuerpo_approve(process_id, request, user, form):
    """Cuerpo síncrono de `approve`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.format_b_service import FormatBService
    from itcj2.apps.titulatec.services.review_presence import ReviewPresence
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, uid, process_id)
        _exigir_bandeja(db, uid)
        if not _operable(db):
            return _bloqueo_por_corte()
        try:
            resultado = FormatBService.approve(db, proc, uid)
        except ValueError as exc:
            # «Ya fue dictaminado por X el …» (otro llegó antes), proceso pausado…
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        ReviewPresence.clear(_PRESENCE_KIND, process_id, uid)
        siguiente = _next_free(db, uid, process_id, _vista(form))
        if resultado.get("completed"):
            aviso = "Formato B aprobado: el proceso quedó completo."
        else:
            aviso = ("Formato B aprobado: el proceso pasó a la fase "
                     f"{int(resultado['next_phase']):02d}.")
        return _repintar(request, db, uid, _vista(form), siguiente, aviso)
    finally:
        db.close()


@router.post("/formato-b/{process_id}/observar", name="titulatec.pages.titulacion.observe")
async def observe(process_id: int, request: Request,
                  user: dict = Depends(require_page_app("titulatec", perms=[_REJECT_PERM]))):
    """Regresa el Formato B al alumno con observaciones (nota general y/o una
    nota por campo marcado, `note__{campo}`)."""
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_observe, process_id=process_id, request=request, user=user, form=form)


def _cuerpo_observe(process_id, request, user, form):
    """Cuerpo síncrono de `observe`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.format_b_service import FormatBService
    from itcj2.apps.titulatec.services.review_presence import ReviewPresence
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    general = form.get("general_note") or ""
    # Las notas vacías no cuentan (el service las ignora): la pantalla puede
    # mandar todas las cajas.
    notas = {k[len(_NOTE_PREFIX):]: v or "" for k, v in form.items()
             if k.startswith(_NOTE_PREFIX)}
    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, uid, process_id)
        _exigir_bandeja(db, uid)
        if not _operable(db):
            return _bloqueo_por_corte()
        try:
            FormatBService.reject(db, proc, uid, general_note=general, field_notes=notas)
        except ValueError as exc:
            # Sin observaciones, campo del registro o nota larga: 400 y el
            # formulario se queda como está (htmx no hace swap en un 4xx).
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        ReviewPresence.clear(_PRESENCE_KIND, process_id, uid)
        siguiente = _next_free(db, uid, process_id, _vista(form))
        return _repintar(request, db, uid, _vista(form), siguiente,
                         "Formato B regresado al alumno con observaciones.")
    finally:
        db.close()


@router.post("/formato-b/{process_id}/registro", name="titulatec.pages.titulacion.registry")
async def registry(process_id: int, request: Request,
                   user: dict = Depends(require_page_app("titulatec", perms=[_CORRECT_PERM]))):
    """Corrige nombre y/o carrera del registro durante la revisión (§8.5, D9)."""
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_registry, process_id=process_id, request=request, user=user, form=form)


def _cuerpo_registry(process_id, request, user, form):
    """Cuerpo síncrono de `registry`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.format_b_service import FormatBService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, uid, process_id)
        _exigir_bandeja(db, uid)
        if not _operable(db):
            return _bloqueo_por_corte()
        try:
            cambios = FormatBService.correct_registry(
                db, proc, uid,
                first_name=form.get("first_name") or "",
                last_name=form.get("last_name") or "",
                middle_name=form.get("middle_name") or None,
                program_id=form.get("program_id") or proc.program_id,
                reason=form.get("reason") or "")
        except ValueError as exc:
            # Motivo vacío, nombre incompleto, otro nivel, sin cambios… 400 con
            # el formulario intacto.
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        partes = [x for x, hay in (
            ("el nombre", any(c != "program_id" for c in cambios)),
            ("la carrera", "program_id" in cambios)) if hay]
        return _repintar(request, db, uid, _vista(form), process_id,
                         f"Se corrigió {' y '.join(partes)} del registro.")
    finally:
        db.close()


# ===========================================================================
# Presencia y documentos
# ===========================================================================
@router.post("/formato-b/{process_id}/viendo", name="titulatec.pages.titulacion.viewing")
def viewing(process_id: int, request: Request,
            user: dict = Depends(require_page_app("titulatec", perms=[_READ_PERM]))):
    """Latido de presencia (cada 60 s desde el detalle abierto, §8.3) → 204.

    Cosmético: con Redis caído `ReviewPresence` no truena y esto sigue en 204.
    """
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


@router.get("/formato-b/{process_id}/documento/{type_code}",
            name="titulatec.pages.titulacion.document")
def document_file(process_id: int, type_code: str, request: Request,
                  user: dict = Depends(require_page_app("titulatec", perms=[_READ_PERM]))):
    """Sirve INLINE un documento de la fase 1 (acta, CURP…) para cotejar el
    nombre (patrón `appointments.py::document_file`). Solo tipos cuyo
    `DocumentType.phase_number` es la fase `initial_docs`: esta vista no abre
    documentos de otras fases."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import DocumentType
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope
    from itcj2.apps.titulatec.utils import storage

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        # Antes de tocar disco: aquí viaja el acta de nacimiento / la CURP.
        proc = assert_process_in_scope(db, uid, process_id)
        _exigir_bandeja(db, uid)
        if not _operable(db):
            return Response(status_code=404)
        fase_1 = PhaseService.phase_number_for_code(db, "initial_docs")
        fase_tipo = (db.query(DocumentType.phase_number)
                     .filter(DocumentType.code == type_code).scalar())
        if fase_1 is None or fase_tipo != fase_1:
            return Response(status_code=404)
        doc = DocumentService.get_document(db, process_id, type_code)
        if not doc:
            return Response(status_code=404)
        path = storage.abs_path(doc.file_path)
        mime = doc.mime_type
        # Mismo nombre que las otras bandejas: `{control}_{ETIQUETA}.{ext}`.
        _period, control = DocumentService._storage_keys(db, proc)
        filename = storage.download_filename(control, type_code, doc.file_path)
    finally:
        db.close()
    if not path.exists():
        return Response(status_code=404)
    return FileResponse(str(path), media_type=mime,
                        headers={"Content-Disposition": f'inline; filename="{filename}"'})
