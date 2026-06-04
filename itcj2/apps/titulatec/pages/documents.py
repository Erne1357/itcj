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


def _doc_row(db, proc):
    from itcj2.core.models.user import User
    from itcj2.core.models.program import Program
    from itcj2.apps.titulatec.models import DocumentType
    from itcj2.apps.titulatec.services.document_service import DocumentService
    u = db.get(User, proc.student_id)
    prog = db.get(Program, proc.program_id) if proc.program_id else None
    docs = []
    pending = 0
    for code in _INITIAL_DOC_TYPES:
        dt = db.query(DocumentType).filter_by(code=code).first()
        doc = DocumentService.get_document(db, proc.id, code)
        status = doc.review_status if doc else "missing"
        if status in ("pending", "missing", "in_review"):
            pending += 1
        docs.append({
            "type_code": code, "name": dt.name if dt else code, "status": status,
            "has_file": doc is not None,
            "view_url": f"/titulatec/admin/documents/{proc.id}/document/{code}" if doc else None,
        })
    return {
        "process_id": proc.id, "folio": proc.folio,
        "student": u.full_name if u else "—", "control": u.control_number if u else "—",
        "program": prog.name if prog else "—",
        "docs": docs, "pending": pending,
        "all_approved": all(d["status"] == "approved" for d in docs),
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
    rows = [_doc_row(db, p) for p in q.order_by(TitulationProcess.created_at.desc()).all()]
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
async def home(request: Request, status: str = "", selected: str = "",
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


@router.post("/{process_id}/document/{type_code}/review", name="titulatec.pages.documents.review")
async def review(process_id: int, type_code: str, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_REVIEW_PERMS))):
    """Aprueba/rechaza un doc; si quedan los 3 aprobados y la fase es 1, auto-avanza a fase 2."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    form = dict(await request.form())
    action = form.get("action")
    note = form.get("note")
    status_filter = form.get("status") or None
    new_status = "approved" if action == "approve" else "rejected"
    db = SessionLocal()
    try:
        DocumentService.review(db, process_id, type_code, status=new_status, note=note,
                               reviewer_id=int(user["sub"]))
        proc = db.get(TitulationProcess, process_id)
        if (proc and proc.current_phase == 1
                and DocumentService.initial_docs_all_approved(db, process_id)):
            PhaseService.approve_phase(db, proc, 1, int(user["sub"]))
        ctx = _body_ctx(db, user_id=int(user["sub"]), status_filter=status_filter,
                        selected_id=process_id)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/documents_body.html", ctx)


@router.get("/{process_id}/document/{type_code}", name="titulatec.pages.documents.file")
async def document_file(process_id: int, type_code: str, request: Request,
                        user: dict = Depends(require_page_app("titulatec", perms=["titulatec.document.api.read.all"]))):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.utils import storage
    db = SessionLocal()
    try:
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
    return FileResponse(str(path), media_type=mime,
                        headers={"Content-Disposition": f'inline; filename="{original}"'})
