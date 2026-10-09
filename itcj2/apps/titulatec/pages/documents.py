"""Bandeja de revisión de documentos iniciales (Servicios Escolares)."""
import dataclasses
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec
from itcj2.apps.titulatec.utils.paging import (
    PAGE_SIZE, Page, normalize_q, paginate_list, parse_page,
)
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("itcj2.apps.titulatec.pages.documents")
router = APIRouter(prefix="/admin/documents", tags=["titulatec-pages-documents"])

_VIEW_PERMS = ["titulatec.document.page.list", "titulatec.dashboard.school_services",
               "titulatec.dashboard.titulaciones", "titulatec.dashboard.admin"]
_REVIEW_PERMS = ["titulatec.document.api.approve", "titulatec.document.api.reject"]


def _exigir_bandeja(db, user_id: int) -> None:
    """Las ACCIONES de esta bandeja exigen poder ABRIRLA (`_VIEW_PERMS`), no solo
    el permiso de la acción: Titulación conserva el dictamen dormido (D1) pero no
    ve esta bandeja ni el desglose (D7, spec 2026-10-07-titulatec-liberados-
    biblioteca-helpdesk-design.md §7). 403 como el gate, ANTES de escribir. Va
    después de `assert_process_in_scope` (`test_scope_guard.py` lo exige primero)."""
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.exceptions import PageForbidden

    if not (cached_perms(db, user_id, "titulatec") & set(_VIEW_PERMS)):
        raise PageForbidden(has_app_access=True)


def _doc_rows(db, procs):
    """Filas COMPLETAS de la bandeja: las dos pasadas seguidas, en **4 consultas fijas**.

    Se conserva como `_doc_present(db, _doc_states(db, procs))` (paginación
    2026-10-04, spec §6): `_body_ctx` ya no la usa -- arma el universo con
    `_doc_states` y presenta solo la página con `_doc_present` --, pero los
    tests de equivalencia y de coste la siguen llamando.

    Historia del coste: antes de 2026-09-02 esto era `_doc_row(db, proc)` dentro
    de una comprension, y cada fila hacia `db.get(User)`, `db.get(Program)` y --
    en un segundo bucle sobre los 3 tipos de documento -- un `DocumentType` por
    codigo mas un `DocumentService.get_document`. Medido sobre los datos de dev
    con el cache de authz caliente: **273 consultas para 28 filas**. Hoy son 4
    pase lo que pase: carreras y documentos (pasada 1), usuarios y tipos (pasada
    2). `test_documents_inbox.py::test_las_filas_de_la_bandeja_cuestan_lo_mismo_con_2_que_con_8`
    lo exige exacto sobre datos homogéneos, sin margen de +1.
    """
    return _doc_present(db, _doc_states(db, procs))


def _doc_states(db, procs):
    """PASADA 1: estado documental de cada proceso, sin usuario ni nombres.

    `procs`: objetos con `id`, `created_at`, `current_phase`, `program_id`,
    `student_id` y `folio` -- un `TitulationProcess` o una fila ligera de
    columnas (`_body_ctx`). Devuelve un dict por proceso, en el MISMO orden:
    `{"process_id", "created_at", "current_phase", "student_id", "program_id",
    "track", "folio", "program_name", "docs": [{"type_code", "status",
    "has_file", "created_at", "mime", "note", "view_url"}], "pending",
    "missing", "all_approved"}`. `pending` cuenta SOLO lo subido sin dictaminar
    («por evaluar»: el número de la fila, la pestaña y el contador); `missing`,
    lo que el alumno no ha subido.

    **Aquí, y solo aquí, vive la regla de estados** (`pending`/`missing`/
    `excused`/`all_approved`): la bandeja filtra, ordena y cuenta sobre estos
    dicts, y `_doc_present` solo les agrega nombres. `folio` y `program_name`
    viajan desde aquí porque salen gratis (la misma fila del proceso y la misma
    lectura de carreras que da el nivel): así la pasada 2 no repite ninguna.

    Consultas fijas: carreras (nivel + nombre), documentos del set en juego y
    -- solo si algún extra de posgrado no tiene fila -- el número de la fase
    `initial_docs`.

    Perfiles mezclados (spec 2026-09-30-titulatec-posgrado-design.md §4.4):
    cada proceso trae SU PROPIO set de códigos (3 en licenciatura, 7 en
    posgrado, vía `DocumentService.initial_doc_types` + `TrackService`), y los
    documentos se leen con la UNIÓN de los códigos en juego -- una consulta,
    con un `IN (...)` más ancho cuando hay posgrado de por medio. Las consultas
    por lote son EXACTAMENTE equivalentes a las de antes: `Document` tiene
    `UNIQUE(process_id, type_code)`.
    """
    from itcj2.core.models.program import Program
    from itcj2.apps.titulatec.models import Document
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.track_service import TrackService

    if not procs:
        return []
    proc_ids = [p.id for p in procs]
    prog_ids = {p.program_id for p in procs if p.program_id}

    # Carreras PRIMERO: la misma fila da el perfil (`.level`) Y el nombre a
    # mostrar, sin una segunda consulta en la pasada 2.
    progs = ({g.id: g for g in db.query(Program.id, Program.level, Program.name)
              .filter(Program.id.in_(prog_ids)).all()} if prog_ids else {})
    tracks_by_pid = {
        p.id: TrackService.for_level(progs[p.program_id].level
                                     if p.program_id in progs else None)
        for p in procs
    }
    codes_by_pid = {pid: DocumentService.initial_doc_types(track)
                    for pid, track in tracks_by_pid.items()}
    all_codes = set()
    for codes in codes_by_pid.values():
        all_codes.update(codes)

    docs = {(d.process_id, d.type_code): d for d in db.query(
        Document.process_id, Document.type_code, Document.review_status,
        Document.created_at, Document.mime_type, Document.review_note)
        .filter(Document.process_id.in_(proc_ids),
                Document.type_code.in_(all_codes)).all()}

    # R-G (spec 2026-09-30-titulatec-posgrado-design.md §5, invariante 8;
    # Ruling R11, revisión final): el numero de la fase `initial_docs` se
    # calcula UNA SOLA VEZ para TODO el lote -- y SOLO si hace falta (algun
    # extra de posgrado sin fila en `docs`) -- para que la bandeja no vuelva
    # a pagar la consulta al catalogo de fases POR FILA. Para un lote
    # homogeneo de licenciatura esta consulta ni se intenta.
    initial_docs_phase = None
    if any((p.id, code) not in docs
           for p in procs
           for code in codes_by_pid[p.id]
           if code in DocumentService.POSGRADO_EXTRA_DOCS):
        initial_docs_phase = PhaseService.phase_number_for_code(db, "initial_docs")

    out = []
    for p in procs:
        codes = codes_by_pid[p.id]
        # `initial_docs_phase` YA resuelto por lote: `excused_initial_docs`
        # (predicado PURO, sin `db`) dice que extras de posgrado se DISPENSAN
        # por R-G. Esos salen con `status="excused"` -- pseudo-estado de la UI,
        # igual que `missing` -- y NO cuentan en `pending` ni impiden
        # `all_approved`.
        present_codes = frozenset(code for code in codes if (p.id, code) in docs)
        excused = DocumentService.excused_initial_docs(
            p, present_codes, initial_docs_phase=initial_docs_phase)
        docs_out = []
        # `pending` = «por evaluar»: archivo SUBIDO esperando dictamen (espera
        # al revisor). `missing` = sin subir (espera al ALUMNO). Antes los dos
        # se sumaban en `pending` y la fila decía «1» sin nada que abrir
        # (2026-10-09, alumno 21111134 en producción).
        pending = 0
        missing = 0
        for code in codes:
            doc = docs.get((p.id, code))
            if doc is None and code in excused:
                status = "excused"
            else:
                status = doc.review_status if doc else "missing"
            if doc is not None and status in ("pending", "in_review"):
                pending += 1
            elif status == "missing":
                missing += 1
            docs_out.append({
                "type_code": code, "status": status,
                "has_file": doc is not None,
                "mime": (doc.mime_type if doc else None) or "application/pdf",
                "note": doc.review_note if doc else None,
                "view_url": f"/titulatec/admin/documents/{p.id}/document/{code}" if doc else None,
                # Respaldo del orden FIFO de "Por evaluar" (`_order_pending_by_wait`)
                # cuando no hay evento en la bitacora. Ningun template lo pinta.
                "created_at": doc.created_at if doc else None,
            })
        prog = progs.get(p.program_id) if p.program_id else None
        out.append({
            "process_id": p.id, "created_at": p.created_at,
            # Lo usa `_annotate_phase_lock` en el detalle.
            "current_phase": p.current_phase,
            "student_id": p.student_id, "program_id": p.program_id,
            # Alimenta la píldora "Posgrado" (`track_pill`, `_macros.html`).
            "track": tracks_by_pid[p.id],
            "folio": p.folio, "program_name": prog.name if prog else None,
            "docs": docs_out, "pending": pending, "missing": missing,
            # Un dispensado (R-G) no bloquea el "listo para agendar cotejo": solo
            # los realmente exigibles -- aprobados o dispensados -- cuentan.
            "all_approved": all(d["status"] in ("approved", "excused") for d in docs_out),
        })
    return out


def _doc_present(db, states):
    """PASADA 2: agrega lo que se PINTA -- alumno, control, carrera, nombres de tipo.

    Solo para las filas de la página (y el detalle seleccionado): consultas
    fijas, usuarios y tipos de documento (`folio` y carrera ya vienen en el
    estado, ver `_doc_states`). No decide ningún estado: copia los de la pasada 1.
    Devuelve dicts NUEVOS (también los de `docs`), así que anotar el detalle
    (`_annotate_phase_lock`) no toca el universo.
    """
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import DocumentType

    if not states:
        return []
    user_ids = {s["student_id"] for s in states if s["student_id"]}
    codes = {d["type_code"] for s in states for d in s["docs"]}
    users = ({u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
             if user_ids else {})
    # Sin filtro `is_active`: si un tipo se desactiva, el documento ya subido
    # debe seguir mostrandose con su nombre y no con el codigo crudo (mismo
    # criterio que `DocumentService.initial_docs_summary`).
    names = {t.code: t.name for t in db.query(DocumentType.code, DocumentType.name)
             .filter(DocumentType.code.in_(codes)).all()}
    out = []
    for s in states:
        u = users.get(s["student_id"])
        out.append({
            **s,
            "student": u.full_name if u else "—",
            "control": u.control_number if u else "—",
            "program": s["program_name"] or "—",
            "docs": [{**d, "name": names.get(d["type_code"], d["type_code"])}
                     for d in s["docs"]],
        })
    return out


def _last_uploads(db, process_ids):
    """Ultima llegada de cada (proceso, tipo) segun la bitacora, en UN lote.

    Delegado a `DocumentService.last_uploads` (Tarea 2, 2026-09-28, plan
    titulatec-correos-notificaciones): la vista del alumno
    (`pages/student.py::_docs_status_ctx`, linea "Enviado el ...") necesita la
    MISMA fuente de verdad de "cuando llego de verdad cada documento", asi que
    la logica se movio al service y aqui solo se reexporta -- misma firma,
    mismos resultados (`test_last_uploads_es_equivalente_al_de_la_bandeja`),
    para no romper a quien ya importa esta funcion desde este modulo
    (`test_documents_fifo.py`, `test_documents_inbox.py`).
    """
    from itcj2.apps.titulatec.services.document_service import DocumentService

    return DocumentService.last_uploads(db, process_ids)


def _order_pending_by_wait(db, rows):
    """Orden de "Por evaluar": FIFO por espera REAL, no por antiguedad del proceso.

    Opera sobre los estados de la pasada 1 (`_doc_states`) -- o sobre filas
    presentadas, que traen las mismas claves --: todo el universo filtrado se
    ordena ANTES de paginar, así que la cola sigue entre páginas.

    La clave de cada fila es el MINIMO, entre sus documentos con archivo en
    `review_status == 'pending'`, de la ultima llegada de cada uno -- el mas
    viejo esperando dictamen entra primero. Sin evento en la bitacora (fila
    sembrada, o subida antes de `2f43e7e5` -- 2026-09-03 --, cuando las subidas
    empezaron a dejar ese evento) el respaldo es `Document.created_at` (ya
    cargado por `_doc_states`, sin consulta extra). Desempate por `process_id`
    ascendente.

    Una fila cuyo unico pendiente fuera "missing" (nada subido: se espera al
    alumno, no al revisor) ya no llega aqui: desde 2026-10-09 `pending` no
    cuenta faltantes y la pestana no la incluye. Si alguna fila llegara sin
    tiempo que medir, va al final SIN reordenarse (`created_at desc, id desc`).

    Una sola consulta por lote (`_last_uploads`); no se llama desde `_doc_states`
    para que las otras 3 pestanas sigan sin pagarla.
    """
    ultimas = _last_uploads(db, [r["process_id"] for r in rows])

    con_espera, sin_espera = [], []
    for r in rows:
        tiempos = [
            ultimas.get((r["process_id"], d["type_code"]), d["created_at"])
            for d in r["docs"] if d["has_file"] and d["status"] == "pending"
        ]
        if tiempos:
            con_espera.append((min(tiempos), r["process_id"], r))
        else:
            sin_espera.append(r)
    con_espera.sort(key=lambda t: (t[0], t[1]))
    return [r for _, _, r in con_espera] + sin_espera


def _annotate_phase_lock(db, detail):
    """Marca el detalle con lo que el panel de dictamen necesita (2026-10-04).

    - `phase_closed`: el proceso ya pasó la fase `initial_docs`. Desde ahí el
      dictamen se congela (`DocumentService.review` lo hace cumplir con
      `PHASE_CLOSED_MSG`): sin Rechazar, y sin Aprobar sobre uno ya aprobado.
    - `closes_phase` por documento: aprobar ESTE cierra la fase (es el único
      del set que falta por aprobar y el proceso sigue en `initial_docs`). La
      plantilla le pone la re-confirmación al botón Aprobar.

    Solo para la fila seleccionada -- una consulta al catálogo de fases, no
    una por fila (los conteos de `_doc_states` no cambian).
    """
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    n = PhaseService.phase_number_for_code(db, "initial_docs")
    current = detail.get("current_phase")
    en_fase = n is not None and current == n
    detail["phase_closed"] = n is not None and isinstance(current, int) and current > n
    faltan = [d for d in detail["docs"] if d["status"] not in ("approved", "excused")]
    for d in detail["docs"]:
        d["closes_phase"] = (en_fase and len(faltan) == 1 and faltan[0] is d
                             and d["has_file"])


def _body_ctx(db, *, user_id, status_filter, selected_id, q=None, page=1,
              per_page: int = PAGE_SIZE):
    """Contexto del parcial, en DOS pasadas (paginación 2026-10-04, spec §6).

    1. Universo ligero: procesos activos en alcance (`officer_programs`, ANTES
       de contar y paginar) y búsqueda (`process_search`, en SQL), solo las
       columnas que pide `_doc_states`. Sobre esos estados, en Python: quitar
       los que no tienen ningún archivo, filtrar la pestaña, ordenar (FIFO en
       «Por evaluar», `_order_pending_by_wait`) y contar `total_pending`.
    2. `paginate_list` (una página fuera de rango cae en la última válida) y
       `_doc_present` SOLO para las ≤`per_page` filas de la página.

    `?selected=`: si el proceso está en el universo filtrado se pinta aunque no
    caiga en la página (se presenta aparte, una pasada 2 de una fila); si no
    está (otra pestaña, otra búsqueda, fuera de alcance) -> `detail=None`.
    """
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.process_service import process_search
    from itcj2.apps.titulatec.services.scope_service import officer_programs
    from itcj2.core.services.authz_cache import cached_perms

    q = normalize_q(q)
    page = parse_page(page)

    # Arreglo A2 (revision final 2026-09-21): mismo criterio que `can_mark_reqs`
    # en `pages/admin.py` -- los botones Aprobar/Rechazar de `documents_body.html`
    # se pintan solo para quien tiene el permiso, no solo por el estado del
    # documento. `_REVIEW_PERMS` es la MISMA lista OR que exige la ruta
    # `POST .../document/review`, asi que "puede verlos" == "puede usarlos".
    can_review_docs = bool(
        user_id is not None
        and cached_perms(db, user_id, "titulatec") & set(_REVIEW_PERMS)
    )
    ctx = {"rows": [], "page": Page(items=[], total=0, page=1, per_page=per_page),
           "total_pending": 0, "status_filter": status_filter or "", "q": q or "",
           "detail": None, "selected_id": None, "can_review_docs": can_review_docs}

    scope = officer_programs(db, user_id)
    TP = TitulationProcess
    uq = db.query(TP.id, TP.created_at, TP.current_phase, TP.program_id,
                  TP.student_id, TP.folio).filter(TP.status == "active")
    if scope != "ALL":
        if not scope:
            return ctx
        uq = uq.filter(TP.program_id.in_(scope))
    search = process_search(q)
    if search is not None:
        uq = uq.outerjoin(User, User.id == TP.student_id).filter(search)
    # Desempate por `id`: `created_at` es `server_default NOW()` y en Postgres
    # NOW() es la hora de INICIO DE LA TRANSACCION, asi que varios procesos
    # creados en la misma (una importacion, por ejemplo) empatan y el orden lo
    # decidiria el planificador -> la lista se re-barajaria sola entre filtros
    # (y, paginada, una fila podría saltar o repetirse entre páginas).
    states = _doc_states(db, uq.order_by(TP.created_at.desc(), TP.id.desc()).all())
    states = [s for s in states if any(d["has_file"] for d in s["docs"])]
    if status_filter == "pending":
        states = [s for s in states if s["pending"] > 0]
        # Unica pestana con orden distinto: FIFO por espera real (ver
        # `_order_pending_by_wait`). Las otras 3 se quedan con el orden de
        # arriba (`created_at desc, id desc`) tal cual.
        states = _order_pending_by_wait(db, states)
    elif status_filter == "rejected":
        states = [s for s in states if any(d["status"] == "rejected" for d in s["docs"])]
    elif status_filter == "approved":
        states = [s for s in states if s["all_approved"]]

    pg = paginate_list(states, page, per_page)
    rows = _doc_present(db, pg.items)
    detail = None
    if selected_id:
        detail = next((r for r in rows if r["process_id"] == selected_id), None)
        if detail is None:
            st = next((s for s in states if s["process_id"] == selected_id), None)
            if st is not None:
                detail = _doc_present(db, [st])[0]
    if detail:
        _annotate_phase_lock(db, detail)
    ctx.update({"rows": rows, "page": dataclasses.replace(pg, items=rows),
                "total_pending": sum(s["pending"] for s in states),
                "detail": detail, "selected_id": selected_id})
    return ctx


def _to_int(raw):
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


@router.get("", name="titulatec.pages.documents.home")
def home(request: Request, status: str = "pending", selected: str = "",
         q: str = "", page: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), status_filter=status or None,
                        selected_id=_to_int(selected), q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/documents.html", ctx)


@router.get("/body", name="titulatec.pages.documents.body")
def body(request: Request, status: str = "", selected: str = "",
         q: str = "", page: str = "",
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), status_filter=status or None,
                        selected_id=_to_int(selected), q=q, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/documents_body.html", ctx)


@router.post("/{process_id}/document/review", name="titulatec.pages.documents.review")
async def review(process_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_REVIEW_PERMS))):
    """Aprueba/rechaza un doc; si queda aprobado el set completo del proceso (3 en
    licenciatura, 7 en posgrado) y la fase es 1, auto-avanza a fase 2 -- ya
    resuelto por `DocumentService.initial_docs_all_approved` (Tarea 3), sin
    cambio de llamada aquí (Tarea 4).
    El tipo de documento llega en el form (type_code), no en la URL (panel de dictamen único)."""
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_review, process_id=process_id, request=request, user=user, form=form)


def _cuerpo_review(process_id, request, user, form):
    """Cuerpo síncrono de `review`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    type_code = form.get("type_code") or ""
    if not type_code:
        return Response(status_code=400, headers={"X-Tt-Error": "Falta el documento a revisar."})
    action = form.get("action")
    note = (form.get("note") or "").strip() or None
    status_filter = form.get("status") or None
    # La acción re-pinta la MISMA pestaña, página y búsqueda (spec 2026-10-04
    # §3.3); si la vació, `paginate_list` cae en la última página válida.
    tab_q, tab_page = form.get("q"), form.get("page")
    new_status = "approved" if action == "approve" else "rejected"
    if new_status == "rejected" and not note:
        return Response(status_code=400, headers={"X-Tt-Error": "Indica el motivo del rechazo y la corrección esperada."})
    db = SessionLocal()
    try:
        # El guard sustituye al `db.get` de mas abajo: dictaminar y, peor, auto-avanzar
        # la fase de un proceso de otra carrera pasaba sin que nada lo mirara.
        proc = assert_process_in_scope(db, int(user["sub"]), process_id)
        _exigir_bandeja(db, int(user["sub"]))
        try:
            DocumentService.review(db, process_id, type_code, status=new_status, note=note,
                                   reviewer_id=int(user["sub"]))
        except ValueError as exc:
            # `PhaseService.HANDOFF_MSG` es ASCII puro (test dedicado en
            # `phase_service`): no hace falta el `_hdr()` de otros archivos.
            return Response(status_code=400, headers={"X-Tt-Error": str(exc)})
        # El auto-avance pasa por la MISMA guarda que el botón manual: `can_transition`
        # incluye `current_phase == 1` y además exige `status == 'active'`, que este
        # camino no miraba (dictaminar un doc empujaba de fase a un proceso cancelado).
        if (proc and DocumentService.initial_docs_all_approved(db, process_id)
                and PhaseService.can_transition(db, proc, 1)):
            PhaseService.approve_phase(db, proc, 1, int(user["sub"]))
        ctx = _body_ctx(db, user_id=int(user["sub"]), status_filter=status_filter,
                        selected_id=process_id, q=tab_q, page=tab_page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/documents_body.html", ctx)


@router.get("/{process_id}/document/{type_code}", name="titulatec.pages.documents.file")
def document_file(process_id: int, type_code: str, request: Request, download: int = 0,
                  user: dict = Depends(require_page_app("titulatec", perms=["titulatec.document.api.read.all"]))):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope
    from itcj2.apps.titulatec.utils import storage
    db = SessionLocal()
    try:
        # Antes de tocar disco: esta ruta admite `?download=1` sobre acta/CURP.
        proc = assert_process_in_scope(db, int(user["sub"]), process_id)
        doc = DocumentService.get_document(db, process_id, type_code)
        if not doc:
            return Response(status_code=404)
        path = storage.abs_path(doc.file_path)
        mime = doc.mime_type
        # `{control}_{ETIQUETA}.{ext}` (2026-09-28), calculado y no leído del
        # disco: un archivo que aún no pasó por `rename-documents` ya se
        # descarga con el nombre nuevo. `original_name` ya no nombra nada.
        _period, control = DocumentService._storage_keys(db, proc)
        filename = storage.download_filename(control, type_code, doc.file_path)
    finally:
        db.close()
    if not path.exists():
        return Response(status_code=404)
    disp = "attachment" if download else "inline"
    return FileResponse(str(path), media_type=mime,
                        headers={"Content-Disposition": f'{disp}; filename="{filename}"'})
