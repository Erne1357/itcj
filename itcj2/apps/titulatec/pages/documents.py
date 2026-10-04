"""Bandeja de revisión de documentos iniciales (Servicios Escolares)."""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.documents")
router = APIRouter(prefix="/admin/documents", tags=["titulatec-pages-documents"])

_VIEW_PERMS = ["titulatec.document.page.list", "titulatec.dashboard.school_services",
               "titulatec.dashboard.titulaciones", "titulatec.dashboard.admin"]
_REVIEW_PERMS = ["titulatec.document.api.approve", "titulatec.document.api.reject"]


def _doc_rows(db, procs):
    """Filas de la bandeja en **4 consultas fijas**, no 4 por fila.

    Antes esto era `_doc_row(db, proc)` dentro de una comprension, y cada fila
    hacia: `db.get(User)`, `db.get(Program)` y — en un segundo bucle sobre los 3
    tipos de documento — un `DocumentType` por codigo mas un
    `DocumentService.get_document`. Medido sobre los datos de dev con el cache
    de authz caliente: **273 consultas para 28 filas** (1 de procesos + 102
    tipos + 102 documentos + 34 usuarios + 34 carreras). Hoy son 5, y el tiempo
    de servidor baja de 112.5 ms a 3.8 ms (mediana de 7 corridas).

    Las dos consultas por lote son EXACTAMENTE equivalentes a las de antes:
    `DocumentType.code` es UNIQUE y `Document` tiene
    `UNIQUE(process_id, type_code)`, asi que el `.first()` de cada fila no podia
    devolver mas de un candidato y el `IN` no depende del orden de Postgres.
    El orden de las filas lo sigue fijando el `order_by` de `_body_ctx`.

    Perfiles mezclados (spec 2026-09-30-titulatec-posgrado-design.md §4.4,
    Tarea 4): cada proceso trae SU PROPIO set de códigos (3 en licenciatura, 7
    en posgrado, vía `DocumentService.initial_doc_types` + `TrackService`), y
    `names`/`docs` se consultan con la UNIÓN de todos los códigos en juego —
    sigue siendo UNA consulta cada una, con un `IN (...)` más ancho cuando hay
    posgrado de por medio. El nivel de la carrera NO paga una consulta aparte:
    sale del mismo `Program` que `progs` ya trae para el nombre a mostrar
    (`TrackService.for_level`, no `TrackService.for_processes`, que repetiría
    esa lectura). El conteo se queda en 4 pase lo que pase —
    `test_documents_inbox.py::test_las_filas_de_la_bandeja_cuestan_lo_mismo_con_2_que_con_8`
    lo exige exacto sobre datos homogéneos, sin margen de +1.
    """
    from itcj2.core.models.user import User
    from itcj2.core.models.program import Program
    from itcj2.apps.titulatec.models import Document, DocumentType
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.track_service import TrackService

    if not procs:
        return []
    proc_ids = [p.id for p in procs]
    user_ids = {p.student_id for p in procs if p.student_id}
    prog_ids = {p.program_id for p in procs if p.program_id}

    # Carreras PRIMERO: el mismo objeto sirve para el nombre a mostrar Y para
    # resolver el perfil (`.level`) de cada fila, sin una segunda consulta.
    progs = ({g.id: g for g in db.query(Program).filter(Program.id.in_(prog_ids)).all()}
             if prog_ids else {})
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

    # Sin filtro `is_active`: si un tipo se desactiva, el documento ya subido
    # debe seguir mostrandose con su nombre y no con el codigo crudo (mismo
    # criterio que `DocumentService.initial_docs_summary`).
    names = {t.code: t.name for t in db.query(DocumentType)
             .filter(DocumentType.code.in_(all_codes)).all()}
    docs = {(d.process_id, d.type_code): d for d in db.query(Document)
            .filter(Document.process_id.in_(proc_ids),
                    Document.type_code.in_(all_codes)).all()}
    users = ({u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
             if user_ids else {})

    # R-G (spec 2026-09-30-titulatec-posgrado-design.md §5, invariante 8;
    # Ruling R11, revisión final): el numero de la fase `initial_docs` se
    # calcula UNA SOLA VEZ para TODO el lote -- y SOLO si hace falta (algun
    # extra de posgrado sin fila en `docs`) -- para que la bandeja no vuelva
    # a pagar la consulta al catalogo de fases POR FILA (el mismo N+1 que el
    # docstring de arriba ya midio y cerro). Para un lote homogeneo de
    # licenciatura `codes_by_pid` nunca trae un codigo de
    # `POSGRADO_EXTRA_DOCS`, asi que esta consulta ni se intenta.
    initial_docs_phase = None
    if any((p.id, code) not in docs
           for p in procs
           for code in codes_by_pid[p.id]
           if code in DocumentService.POSGRADO_EXTRA_DOCS):
        initial_docs_phase = PhaseService.phase_number_for_code(db, "initial_docs")

    return [_doc_row(p, users=users, progs=progs, names=names, docs=docs,
                     codes=codes_by_pid[p.id], track=tracks_by_pid[p.id],
                     initial_docs_phase=initial_docs_phase)
            for p in procs]


def _doc_row(proc, *, users, progs, names, docs, codes, track, initial_docs_phase=None):
    """Fila de la bandeja. Sin `db`: los catalogos llegan ya resueltos (`_doc_rows`).

    `codes` y `track` son los del PROPIO proceso (perfil ya resuelto en
    `_doc_rows`): licenciatura y "sin carrera" traen los 3 de siempre;
    posgrado, los 7. `track` alimenta la píldora "Posgrado" de la plantilla
    (`track_pill`, `_macros.html`) — vacío para cualquier otro valor.

    `initial_docs_phase` (Ruling R11, revisión final): el numero de fase de
    `initial_docs` YA resuelto por `_doc_rows` (una vez por lote, o `None` si
    el lote no lo necesito). Con el, y los codigos que SI tienen fila en
    `docs`, `DocumentService.excused_initial_docs` (predicado PURO, sin `db`)
    dice que extras de posgrado se DISPENSAN por R-G: esos salen con
    `status="excused"` -- pseudo-estado de la UI, igual que `missing` -- y NO
    cuentan en `pending` ni impiden `all_approved`.
    """
    from itcj2.apps.titulatec.services.document_service import DocumentService

    u = users.get(proc.student_id)
    prog = progs.get(proc.program_id) if proc.program_id else None
    present_codes = frozenset(code for code in codes if (proc.id, code) in docs)
    excused = DocumentService.excused_initial_docs(
        proc, present_codes, initial_docs_phase=initial_docs_phase)
    docs_out = []
    pending = 0
    for code in codes:
        doc = docs.get((proc.id, code))
        if doc is None and code in excused:
            status = "excused"
        else:
            status = doc.review_status if doc else "missing"
        if status in ("pending", "missing", "in_review"):
            pending += 1
        docs_out.append({
            "type_code": code, "name": names.get(code, code), "status": status,
            "has_file": doc is not None,
            "mime": (doc.mime_type if doc else None) or "application/pdf",
            "note": doc.review_note if doc else None,
            "view_url": f"/titulatec/admin/documents/{proc.id}/document/{code}" if doc else None,
            # Respaldo del orden FIFO de "Por evaluar" (`_order_pending_by_wait`)
            # cuando no hay evento en la bitacora. Ningun template lo pinta, y
            # no cuesta consulta: ya viene en el lote de `docs` de `_doc_rows`.
            "created_at": doc.created_at if doc else None,
        })
    return {
        "process_id": proc.id, "folio": proc.folio,
        "student": u.full_name if u else "—", "control": u.control_number if u else "—",
        "program": prog.name if prog else "—",
        "track": track,
        # Sin consulta: ya viene en el proceso. Lo usa `_annotate_phase_lock`.
        "current_phase": proc.current_phase,
        "docs": docs_out, "pending": pending,
        # Un dispensado (R-G) no bloquea el "listo para agendar cotejo": solo
        # los realmente exigibles -- aprobados o dispensados -- cuentan.
        "all_approved": all(d["status"] in ("approved", "excused") for d in docs_out),
    }


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

    La clave de cada fila es el MINIMO, entre sus documentos con archivo en
    `review_status == 'pending'`, de la ultima llegada de cada uno -- el mas
    viejo esperando dictamen entra primero. Sin evento en la bitacora (fila
    sembrada, o subida antes de `2f43e7e5` -- 2026-09-03 --, cuando las subidas
    empezaron a dejar ese evento) el respaldo es `Document.created_at` (ya
    cargado por `_doc_row`, sin consulta extra). Desempate por `process_id`
    ascendente.

    Las filas cuyo unico pendiente es "missing" (nada subido: se espera al
    alumno, no al revisor) no tienen ningun tiempo que medir -- van al final,
    SIN reordenarse entre si, asi que conservan el orden que traian
    (`created_at desc, id desc`).

    Una sola consulta por lote (`_last_uploads`); no se llama desde `_doc_rows`
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
    una por fila (los conteos de `_doc_rows` no cambian).
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


def _body_ctx(db, *, user_id, status_filter, selected_id):
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.scope_service import officer_programs
    from itcj2.core.services.authz_service import get_user_permissions_for_app

    # Arreglo A2 (revision final 2026-09-21): mismo criterio que `can_mark_reqs`
    # en `pages/admin.py` -- los botones Aprobar/Rechazar de `documents_body.html`
    # se pintan solo para quien tiene el permiso, no solo por el estado del
    # documento. `_REVIEW_PERMS` es la MISMA lista OR que exige la ruta
    # `POST .../document/review`, asi que "puede verlos" == "puede usarlos".
    can_review_docs = bool(
        user_id is not None
        and get_user_permissions_for_app(db, user_id, "titulatec") & set(_REVIEW_PERMS)
    )

    scope = officer_programs(db, user_id)
    q = db.query(TitulationProcess).filter(TitulationProcess.status == "active")
    if scope != "ALL":
        if not scope:
            return {"rows": [], "total_pending": 0, "status_filter": status_filter or "",
                    "detail": None, "selected_id": None, "can_review_docs": can_review_docs}
        q = q.filter(TitulationProcess.program_id.in_(scope))
    # Desempate por `id`: `created_at` es `server_default NOW()` y en Postgres
    # NOW() es la hora de INICIO DE LA TRANSACCION, asi que varios procesos
    # creados en la misma (una importacion, por ejemplo) empatan y el orden lo
    # decidiria el planificador -> la lista se re-barajaria sola entre filtros.
    # Sobre los datos de hoy, con 34 `created_at` distintos, no cambia nada:
    # comprobado byte a byte contra el HTML de antes.
    rows = _doc_rows(db, q.order_by(TitulationProcess.created_at.desc(),
                                    TitulationProcess.id.desc()).all())
    rows = [r for r in rows if any(d["has_file"] for d in r["docs"])]
    if status_filter == "pending":
        rows = [r for r in rows if r["pending"] > 0]
        # Unica pestana con orden distinto: FIFO por espera real (ver
        # `_order_pending_by_wait`). Las otras 3 se quedan con el orden de
        # arriba (`created_at desc, id desc`) tal cual.
        rows = _order_pending_by_wait(db, rows)
    elif status_filter == "rejected":
        rows = [r for r in rows if any(d["status"] == "rejected" for d in r["docs"])]
    elif status_filter == "approved":
        rows = [r for r in rows if r["all_approved"]]
    total_pending = sum(r["pending"] for r in rows)
    detail = next((r for r in rows if r["process_id"] == selected_id), None) if selected_id else None
    if detail:
        _annotate_phase_lock(db, detail)
    return {"rows": rows, "total_pending": total_pending,
            "status_filter": status_filter or "", "detail": detail, "selected_id": selected_id,
            "can_review_docs": can_review_docs}


def _to_int(raw):
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


@router.get("", name="titulatec.pages.documents.home")
async def home(request: Request, status: str = "pending", selected: str = "",
               user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), status_filter=status or None,
                        selected_id=_to_int(selected))
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/documents.html", ctx)


@router.get("/body", name="titulatec.pages.documents.body")
async def body(request: Request, status: str = "", selected: str = "",
               user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS))):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, user_id=int(user["sub"]), status_filter=status or None,
                        selected_id=_to_int(selected))
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
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    form = dict(await request.form())
    type_code = form.get("type_code") or ""
    if not type_code:
        return Response(status_code=400, headers={"X-Tt-Error": "Falta el documento a revisar."})
    action = form.get("action")
    note = (form.get("note") or "").strip() or None
    status_filter = form.get("status") or None
    new_status = "approved" if action == "approve" else "rejected"
    if new_status == "rejected" and not note:
        return Response(status_code=400, headers={"X-Tt-Error": "Indica el motivo del rechazo y la corrección esperada."})
    db = SessionLocal()
    try:
        # El guard sustituye al `db.get` de mas abajo: dictaminar y, peor, auto-avanzar
        # la fase de un proceso de otra carrera pasaba sin que nada lo mirara.
        proc = assert_process_in_scope(db, int(user["sub"]), process_id)
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
                        selected_id=process_id)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/documents_body.html", ctx)


@router.get("/{process_id}/document/{type_code}", name="titulatec.pages.documents.file")
async def document_file(process_id: int, type_code: str, request: Request, download: int = 0,
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
