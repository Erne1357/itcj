"""Páginas administrativas de TitulaTec (desktop, bandeja tipo email)."""
import logging
import secrets

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec, get_titulatec_roles

logger = logging.getLogger("itcj2.apps.titulatec.pages.admin")

router = APIRouter(prefix="/admin", tags=["titulatec-pages-admin"])

# Permiso para gestionar convocatorias / importar (Servicios Escolares + admin).
_COHORT_PERMS = [
    "titulatec.cohort.api.import_csv", "titulatec.cohort.page.list",
    "titulatec.dashboard.admin", "titulatec.dashboard.school_services",
]

# Ver procesos (bandeja/detalle): cualquier rol admin de la app.
_PROCESS_VIEW_PERMS = [
    "titulatec.process.page.list", "titulatec.process.page.detail",
    "titulatec.process.api.read.all",
    "titulatec.dashboard.admin", "titulatec.dashboard.school_services", "titulatec.dashboard.titulaciones",
]


def _programs(db):
    from itcj2.core.models.program import Program
    return [{"id": p.id, "name": p.name} for p in db.query(Program).order_by(Program.name).all()]


def _modalities(db):
    from itcj2.apps.titulatec.models import Modality
    return [{"id": m.id, "name": m.name} for m in db.query(Modality).filter_by(is_active=True).order_by(Modality.id).all()]

_ROLE_LABELS = {
    "titulatec_titulaciones": "Titulaciones",
    "titulatec_school_services": "Servicios Escolares",
    "admin": "Administración",
}


@router.get("/", name="titulatec.pages.admin.home")
async def home(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=[
        "titulatec.dashboard.titulaciones",
        "titulatec.dashboard.school_services",
        "titulatec.dashboard.admin",
        "titulatec.process.page.list",
    ])),
):
    """Bandeja administrativa. Shell de Fase 0."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import Cohort, TitulationProcess

    roles = get_titulatec_roles(int(user["sub"]))
    role_label = next((lbl for r, lbl in _ROLE_LABELS.items() if r in roles), "Administración")

    db = SessionLocal()
    try:
        stats = {
            "active": db.query(TitulationProcess).filter_by(status="active").count(),
            "pending": db.query(TitulationProcess).filter_by(status="active").count(),
            "cohorts": db.query(Cohort).count(),
            "completed": db.query(TitulationProcess).filter_by(status="completed").count(),
        }
    finally:
        db.close()

    return render_titulatec(request, "titulatec/admin/dashboard.html", {
        "role_label": role_label,
        "stats": stats,
    })


# ===========================================================================
# Convocatorias (cohorts)
# ===========================================================================

@router.get("/cohorts", name="titulatec.pages.admin.cohorts")
async def cohorts(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=_COHORT_PERMS)),
):
    """Lista de convocatorias + alta (selecciona período académico)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import Cohort, TitulationProcess
    from itcj2.core.models.academic_period import AcademicPeriod

    db = SessionLocal()
    try:
        rows = []
        for c in db.query(Cohort).order_by(Cohort.id.desc()).all():
            rows.append({
                "id": c.id, "name": c.name, "status": c.status,
                "period_code": c.period_code,
                "processes": db.query(TitulationProcess).filter_by(cohort_id=c.id).count(),
            })
        used = {c.period_id for c in db.query(Cohort).all()}
        periods = [
            {"id": p.id, "code": p.code, "name": p.name}
            for p in db.query(AcademicPeriod).order_by(AcademicPeriod.id.desc()).all()
            if p.id not in used
        ]
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/cohorts.html", {
        "cohorts": rows, "periods": periods,
    })


@router.post("/cohorts", name="titulatec.pages.admin.cohort_create")
async def cohort_create(
    request: Request,
    period_id: int = Form(...),
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.cohort.api.create"])),
):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import Cohort
    from itcj2.core.models.academic_period import AcademicPeriod

    db = SessionLocal()
    try:
        if not db.query(Cohort).filter_by(period_id=period_id).first():
            period = db.get(AcademicPeriod, period_id)
            db.add(Cohort(
                period_id=period_id,
                name=f"Convocatoria Titulación {period.code if period else period_id}",
                status="open", created_by_id=int(user["sub"]),
            ))
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/titulatec/admin/cohorts", status_code=303)


# ===========================================================================
# Importación de alumnos (CSV del Forms, flexible)
# ===========================================================================

def _preview_ctx(db, cohort_id, token, headers, mapping, rows):
    from itcj2.apps.titulatec.services.import_service import ImportService, TARGET_FIELDS
    preview = ImportService.build_preview(db, rows, mapping)
    importable = sum(1 for r in preview if r["status"] != "error")
    return {
        "cohort_id": cohort_id, "token": token, "headers": headers,
        "mapping": mapping, "fields": TARGET_FIELDS, "preview": preview,
        "programs": _programs(db), "modalities": _modalities(db),
        "total": len(preview), "importable": importable,
        "warnings": sum(1 for r in preview if r["status"] == "warning"),
        "errors": sum(1 for r in preview if r["status"] == "error"),
    }


@router.get("/cohorts/{cohort_id}/import", name="titulatec.pages.admin.import_page")
async def import_page(
    cohort_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=_COHORT_PERMS)),
):
    """Página del asistente de importación (paso 1: subir CSV)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import Cohort

    db = SessionLocal()
    try:
        cohort = db.get(Cohort, cohort_id)
        ctx = {"cohort": cohort.to_dict() if cohort else None}
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/import.html", ctx)


@router.post("/cohorts/{cohort_id}/import/upload", name="titulatec.pages.admin.import_upload")
async def import_upload(
    cohort_id: int,
    request: Request,
    archivo: UploadFile = File(...),
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.cohort.api.import_csv"])),
):
    """Sube el CSV, auto-detecta el mapeo y devuelve el parcial de preview (HTMX)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.import_service import ImportService

    raw = await archivo.read()
    token = secrets.token_hex(8)
    ImportService.save_temp(raw, token)
    headers, rows = ImportService.parse(raw)
    mapping = ImportService.autodetect_mapping(headers)

    db = SessionLocal()
    try:
        ctx = _preview_ctx(db, cohort_id, token, headers, mapping, rows)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/import_preview.html", ctx)


@router.post("/cohorts/{cohort_id}/import/revalidate", name="titulatec.pages.admin.import_revalidate")
async def import_revalidate(
    cohort_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.cohort.api.import_csv"])),
):
    """Reaplica el mapeo (ajuste manual) y devuelve preview actualizado (HTMX)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.import_service import ImportService, TARGET_FIELDS

    form = dict(await request.form())
    token = form.get("token", "")
    raw = ImportService.read_temp(token)
    if not raw:
        return Response(status_code=409)
    headers, rows = ImportService.parse(raw)
    mapping = {f: form.get(f"map_{f}", "") for f in TARGET_FIELDS}

    db = SessionLocal()
    try:
        ctx = _preview_ctx(db, cohort_id, token, headers, mapping, rows)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/import_preview.html", ctx)


@router.post("/cohorts/{cohort_id}/import/commit", name="titulatec.pages.admin.import_commit")
async def import_commit(
    cohort_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.cohort.api.import_csv"])),
):
    """Crea usuarios/procesos a partir de las filas editadas del preview (HTMX)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import Cohort
    from itcj2.apps.titulatec.services.import_service import ImportService, TARGET_FIELDS

    form = dict(await request.form())
    token = form.get("token", "")

    # Reconstruye las filas desde los inputs editables: row-{idx}-{campo}
    idxs = sorted({int(k.split("-")[1]) for k in form if k.startswith("row-") and k.split("-")[1].isdigit()})
    rows = []
    for i in idxs:
        if form.get(f"row-{i}-include") != "on":
            continue
        rows.append({
            "control_number": form.get(f"row-{i}-control_number", ""),
            "full_name": form.get(f"row-{i}-full_name", ""),
            "email": form.get(f"row-{i}-email", ""),
            "program_id": int(form[f"row-{i}-program_id"]) if form.get(f"row-{i}-program_id") else None,
            "modality_id": int(form[f"row-{i}-modality_id"]) if form.get(f"row-{i}-modality_id") else None,
        })

    db = SessionLocal()
    try:
        cohort = db.get(Cohort, cohort_id)
        if not cohort:
            return Response(status_code=404)
        # guarda el mapeo usado para reusarlo la próxima vez
        ImportService.save_mapping({f: form.get(f"map_{f}", "") for f in TARGET_FIELDS})
        summary = ImportService.import_rows(db, cohort, rows)
    finally:
        db.close()
    if token:
        ImportService.delete_temp(token)
    return render_titulatec(request, "titulatec/partials/import_success.html", {
        "summary": summary, "cohort_id": cohort_id,
    })


# ===========================================================================
# Bandeja de procesos + revisión (aprobar/rechazar documentos y fases)
# ===========================================================================

_INITIAL_DOC_TYPES = ["birth_certificate", "high_school_cert", "curp"]


def _detail_ctx(db, process_id: int) -> dict | None:
    from itcj2.core.models.user import User
    from itcj2.core.models.program import Program
    from itcj2.apps.titulatec.models import (
        TitulationProcess, Modality, Cohort, DocumentType, PhaseDefinition,
    )
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.format_b_service import FormatBService
    from itcj2.apps.titulatec.models import FormatB

    proc = db.get(TitulationProcess, process_id)
    if not proc:
        return None
    student = db.get(User, proc.student_id)
    cohort = db.get(Cohort, proc.cohort_id)
    modality = db.get(Modality, proc.modality_id) if proc.modality_id else None
    program = db.get(Program, proc.program_id) if proc.program_id else None

    defs = {d.number: d.name for d in db.query(PhaseDefinition).all()}
    phases = [
        {"number": ph.phase_number, "name": defs.get(ph.phase_number, f"Fase {ph.phase_number}"),
         "status": ph.status, "rejection_reason": ph.rejection_reason}
        for ph in PhaseService.get_phases(db, process_id)
    ]

    initial_docs = []
    for code in _INITIAL_DOC_TYPES:
        dt = db.query(DocumentType).filter_by(code=code).first()
        doc = DocumentService.get_document(db, process_id, code)
        initial_docs.append({
            "type_code": code, "name": dt.name if dt else code,
            "doc": ({"original_name": doc.original_name, "review_status": doc.review_status,
                     "size_bytes": doc.size_bytes or 0, "review_note": doc.review_note} if doc else None),
        })

    fb_row = db.get(FormatB, process_id)
    formato_b = None
    if fb_row and fb_row.status != "draft":
        formato_b = {"status": fb_row.status, "datos": FormatBService.to_ctx(fb_row),
                     "program_name": program.name if program else None}

    return {
        "process": proc.to_dict(),
        "student": {
            "name": student.full_name if student else "—",
            "control": student.control_number if student else "—",
            "email": student.email if student else None,
        },
        "cohort_period": cohort.period_code if cohort else None,
        "program_name": program.name if program else None,
        "modality_name": modality.name if modality else None,
        "phases": phases,
        "current_phase": proc.current_phase,
        "initial_docs": initial_docs,
        "formato_b": formato_b,
    }


@router.get("/processes", name="titulatec.pages.admin.processes")
async def processes(
    request: Request,
    status: str = "",
    view: str = "board",
    user: dict = Depends(require_page_app("titulatec", perms=_PROCESS_VIEW_PERMS)),
):
    """Bandeja de procesos (tablero kanban o tabla, con filtro por estado)."""
    from itcj2.database import SessionLocal
    from itcj2.core.models.user import User
    from itcj2.core.models.program import Program
    from itcj2.apps.titulatec.models import TitulationProcess, PhaseDefinition
    from itcj2.apps.titulatec.services.scope_service import officer_programs

    view = "table" if view == "table" else "board"

    db = SessionLocal()
    try:
        scope = officer_programs(db, int(user["sub"]))
        q = db.query(TitulationProcess)
        if scope != "ALL":
            if not scope:
                return render_titulatec(request, "titulatec/admin/processes.html", {
                    "rows": [], "status": status, "view": view, "columns": [],
                })
            q = q.filter(TitulationProcess.program_id.in_(scope))
        if status:
            q = q.filter_by(status=status)
        defs = {d.number: d.name for d in db.query(PhaseDefinition).all()}
        rows = []
        for p in q.order_by(TitulationProcess.created_at.desc()).all():
            u = db.get(User, p.student_id)
            prog = db.get(Program, p.program_id) if p.program_id else None
            rows.append({
                "id": p.id, "folio": p.folio,
                "student": u.full_name if u else "—",
                "control": u.control_number if u else "—",
                "program": prog.name if prog else "—",
                "phase": p.current_phase, "phase_name": defs.get(p.current_phase, ""),
                "status": p.status,
            })
        phase_defs = db.query(PhaseDefinition).filter_by(is_active=True).order_by(PhaseDefinition.order_index).all()
        buckets = {ph.number: [] for ph in phase_defs}
        for r in rows:
            buckets.setdefault(r["phase"], []).append(r)
        columns = [
            {"number": ph.number, "name": ph.name, "cards": buckets.get(ph.number, [])}
            for ph in phase_defs
        ]
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/processes.html", {
        "rows": rows, "status": status, "view": view, "columns": columns,
    })


@router.get("/processes/{process_id}", name="titulatec.pages.admin.process_detail")
async def process_detail(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=_PROCESS_VIEW_PERMS)),
):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _detail_ctx(db, process_id)
        if not ctx:
            return Response(status_code=404)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/process_detail.html", ctx)


def _render_detail_body(request, db, process_id):
    return render_titulatec(request, "titulatec/partials/admin_process_detail.html", _detail_ctx(db, process_id))


@router.post("/processes/{process_id}/documents/{type_code}/review", name="titulatec.pages.admin.doc_review")
async def doc_review(
    process_id: int,
    type_code: str,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=[
        "titulatec.document.api.approve", "titulatec.document.api.reject"])),
):
    """Aprueba/rechaza un documento. Devuelve el detalle re-renderizado (HTMX)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.document_service import DocumentService

    form = dict(await request.form())
    action = form.get("action")
    note = form.get("note")
    status = "approved" if action == "approve" else "rejected"
    db = SessionLocal()
    try:
        DocumentService.review(db, process_id, type_code, status=status, note=note, reviewer_id=int(user["sub"]))
        return _render_detail_body(request, db, process_id)
    finally:
        db.close()


@router.post("/processes/{process_id}/format-b/review", name="titulatec.pages.admin.fb_review")
async def fb_review(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=[
        "titulatec.format_b.api.approve", "titulatec.format_b.api.reject"])),
):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import FormatB
    from itcj2.apps.titulatec.services.format_b_service import FormatBService

    form = dict(await request.form())
    action = form.get("action")
    note = form.get("note")
    status = "approved" if action == "approve" else "rejected"
    db = SessionLocal()
    try:
        fb = db.get(FormatB, process_id)
        if fb:
            FormatBService.review(db, fb, status=status, note=note, reviewer_id=int(user["sub"]))
        return _render_detail_body(request, db, process_id)
    finally:
        db.close()


@router.post("/processes/{process_id}/phase/{n}/approve", name="titulatec.pages.admin.phase_approve")
async def phase_approve(
    process_id: int,
    n: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.process.api.approve_phase"])),
):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    db = SessionLocal()
    try:
        proc = db.get(TitulationProcess, process_id)
        if proc:
            PhaseService.approve_phase(db, proc, n, int(user["sub"]))
        return _render_detail_body(request, db, process_id)
    finally:
        db.close()


@router.post("/processes/{process_id}/phase/{n}/reject", name="titulatec.pages.admin.phase_reject")
async def phase_reject(
    process_id: int,
    n: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.process.api.reject_phase"])),
):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import TitulationProcess
    from itcj2.apps.titulatec.services.phase_service import PhaseService

    form = dict(await request.form())
    reason = form.get("reason", "")
    db = SessionLocal()
    try:
        proc = db.get(TitulationProcess, process_id)
        if proc:
            PhaseService.reject_phase(db, proc, n, int(user["sub"]), reason)
        return _render_detail_body(request, db, process_id)
    finally:
        db.close()
