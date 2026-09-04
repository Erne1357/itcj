"""Bandeja de revisión de documentos iniciales (Servicios Escolares)."""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.documents")
router = APIRouter(prefix="/admin/documents", tags=["titulatec-pages-documents"])

_INITIAL_DOC_TYPES = ["birth_certificate", "high_school_cert", "curp"]
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
    """
    from itcj2.core.models.user import User
    from itcj2.core.models.program import Program
    from itcj2.apps.titulatec.models import Document, DocumentType

    if not procs:
        return []
    proc_ids = [p.id for p in procs]
    user_ids = {p.student_id for p in procs if p.student_id}
    prog_ids = {p.program_id for p in procs if p.program_id}

    # Sin filtro `is_active`: si un tipo se desactiva, el documento ya subido
    # debe seguir mostrandose con su nombre y no con el codigo crudo (mismo
    # criterio que `DocumentService.initial_docs_summary`).
    names = {t.code: t.name for t in db.query(DocumentType)
             .filter(DocumentType.code.in_(_INITIAL_DOC_TYPES)).all()}
    docs = {(d.process_id, d.type_code): d for d in db.query(Document)
            .filter(Document.process_id.in_(proc_ids),
                    Document.type_code.in_(_INITIAL_DOC_TYPES)).all()}
    users = ({u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
             if user_ids else {})
    progs = ({g.id: g for g in db.query(Program).filter(Program.id.in_(prog_ids)).all()}
             if prog_ids else {})

    return [_doc_row(p, users=users, progs=progs, names=names, docs=docs) for p in procs]


def _doc_row(proc, *, users, progs, names, docs):
    """Fila de la bandeja. Sin `db`: los catalogos llegan ya resueltos (`_doc_rows`)."""
    u = users.get(proc.student_id)
    prog = progs.get(proc.program_id) if proc.program_id else None
    docs_out = []
    pending = 0
    for code in _INITIAL_DOC_TYPES:
        doc = docs.get((proc.id, code))
        status = doc.review_status if doc else "missing"
        if status in ("pending", "missing", "in_review"):
            pending += 1
        docs_out.append({
            "type_code": code, "name": names.get(code, code), "status": status,
            "has_file": doc is not None,
            "mime": (doc.mime_type if doc else None) or "application/pdf",
            "note": doc.review_note if doc else None,
            "view_url": f"/titulatec/admin/documents/{proc.id}/document/{code}" if doc else None,
        })
    return {
        "process_id": proc.id, "folio": proc.folio,
        "student": u.full_name if u else "—", "control": u.control_number if u else "—",
        "program": prog.name if prog else "—",
        "docs": docs_out, "pending": pending,
        "all_approved": all(d["status"] == "approved" for d in docs_out),
    }


def _body_ctx(db, *, user_id, status_filter, selected_id):
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.scope_service import officer_programs
    scope = officer_programs(db, user_id)
    q = db.query(TitulationProcess).filter(TitulationProcess.status == "active")
    if scope != "ALL":
        if not scope:
            return {"rows": [], "total_pending": 0, "status_filter": status_filter or "",
                    "detail": None, "selected_id": None}
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
    elif status_filter == "rejected":
        rows = [r for r in rows if any(d["status"] == "rejected" for d in r["docs"])]
    elif status_filter == "approved":
        rows = [r for r in rows if r["all_approved"]]
    total_pending = sum(r["pending"] for r in rows)
    detail = next((r for r in rows if r["process_id"] == selected_id), None) if selected_id else None
    return {"rows": rows, "total_pending": total_pending,
            "status_filter": status_filter or "", "detail": detail, "selected_id": selected_id}


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
    """Aprueba/rechaza un doc; si quedan los 3 aprobados y la fase es 1, auto-avanza a fase 2.
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
        DocumentService.review(db, process_id, type_code, status=new_status, note=note,
                               reviewer_id=int(user["sub"]))
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
        assert_process_in_scope(db, int(user["sub"]), process_id)
        doc = DocumentService.get_document(db, process_id, type_code)
        if not doc:
            return Response(status_code=404)
        path = storage.abs_path(doc.file_path)
        mime = doc.mime_type
        original = doc.original_name
    finally:
        db.close()
    if not path.exists():
        return Response(status_code=404)
    disp = "attachment" if download else "inline"
    return FileResponse(str(path), media_type=mime,
                        headers={"Content-Disposition": f'{disp}; filename="{original or type_code}"'})
