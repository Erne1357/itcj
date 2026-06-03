"""Páginas del alumno en TitulaTec (mobile-first)."""
import logging

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.student")

router = APIRouter(prefix="/student", tags=["titulatec-pages-student"])

# Documentos de la fase 1 (iniciales). egel_proof solo aplica a modalidad EGEL.
_INITIAL_DOC_TYPES = ["birth_certificate", "high_school_cert", "curp"]


def _slot_ctx(dtype, doc, *, error: str | None = None) -> dict:
    """Contexto autónomo de un slot de documento para el parcial."""
    return {
        "dtype": {"code": dtype.code, "name": dtype.name, "file_kind": dtype.file_kind},
        "doc": ({
            "review_status": doc.review_status,
            "original_name": doc.original_name,
            "mime_type": doc.mime_type,
            "size_bytes": doc.size_bytes or 0,
            "version": doc.version,
        } if doc else None),
        "upload_url": f"/titulatec/student/documents/{dtype.code}",
        "delete_url": f"/titulatec/student/documents/{dtype.code}",
        "error": error,
    }


@router.get("/dashboard", name="titulatec.pages.student.dashboard")
async def dashboard(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.dashboard.student"])),
):
    """Dashboard del alumno (Variante D). Shell de Fase 0."""
    from itcj2.database import SessionLocal
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import PhaseDefinition, TitulationProcess

    db = SessionLocal()
    try:
        user_id = int(user["sub"])
        u = db.get(User, user_id)
        phases = (
            db.query(PhaseDefinition)
            .filter_by(is_active=True)
            .order_by(PhaseDefinition.order_index)
            .all()
        )
        process = (
            db.query(TitulationProcess)
            .filter_by(student_id=user_id)
            .order_by(TitulationProcess.created_at.desc())
            .first()
        )
        current_phase = process.current_phase if process else 0
        phase_name = None
        if process:
            pd = next((p for p in phases if p.number == current_phase), None)
            phase_name = pd.name if pd else None
        progress_pct = int(round(current_phase / 9 * 100)) if process else 0

        ctx = {
            "first_name": u.first_name if u else None,
            "phases": [p.to_dict() for p in phases],
            "current_phase": current_phase,
            "progress_pct": progress_pct,
            "phase_name": phase_name,
        }
    finally:
        db.close()

    return render_titulatec(request, "titulatec/student/dashboard.html", ctx)


@router.get("/documents", name="titulatec.pages.student.documents")
async def documents(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.document.api.read.own"])),
):
    """Página de documentos iniciales (fase 1) con dropzones HTMX."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import DocumentType
    from itcj2.apps.titulatec.services.document_service import DocumentService

    db = SessionLocal()
    try:
        process = DocumentService.get_active_process(db, int(user["sub"]))
        slots = []
        if process:
            for code in _INITIAL_DOC_TYPES:
                dtype = db.query(DocumentType).filter_by(code=code, is_active=True).first()
                if not dtype:
                    continue
                doc = DocumentService.get_document(db, process.id, code)
                slots.append(_slot_ctx(dtype, doc))
        all_uploaded = bool(slots) and all(s["doc"] for s in slots)
        ctx = {
            "process": process.to_dict() if process else None,
            "slots": slots,
            "all_uploaded": all_uploaded,
        }
    finally:
        db.close()

    return render_titulatec(request, "titulatec/student/documents.html", ctx)


@router.post("/documents/{type_code}", name="titulatec.pages.student.document_upload")
async def document_upload(
    type_code: str,
    request: Request,
    archivo: UploadFile = File(...),
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.document.api.upload.own"])),
):
    """Sube/sobreescribe un documento. Devuelve el parcial del slot (HTMX)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import DocumentType
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.utils.storage import StorageError

    db = SessionLocal()
    try:
        dtype = db.query(DocumentType).filter_by(code=type_code, is_active=True).first()
        if not dtype:
            return Response(status_code=404)
        process = DocumentService.get_active_process(db, int(user["sub"]))
        if not process:
            return Response(status_code=409)

        raw = await archivo.read()
        error = None
        doc = DocumentService.get_document(db, process.id, type_code)
        try:
            doc = DocumentService.save(
                db, process, type_code,
                raw=raw, original_name=archivo.filename,
                content_type=archivo.content_type, uploaded_by_id=int(user["sub"]),
            )
        except (StorageError, ValueError) as exc:
            error = str(exc)

        ctx = _slot_ctx(dtype, doc, error=error)
        resp = render_titulatec(request, "titulatec/partials/document_slot.html", ctx)
        if error:
            resp.headers["X-Tt-Error"] = error
        return resp
    finally:
        db.close()


@router.delete("/documents/{type_code}", name="titulatec.pages.student.document_delete")
async def document_delete(
    type_code: str,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.document.api.delete.own"])),
):
    """Elimina un documento. Devuelve el parcial del slot vacío (HTMX)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import DocumentType
    from itcj2.apps.titulatec.services.document_service import DocumentService

    db = SessionLocal()
    try:
        dtype = db.query(DocumentType).filter_by(code=type_code, is_active=True).first()
        if not dtype:
            return Response(status_code=404)
        process = DocumentService.get_active_process(db, int(user["sub"]))
        if process:
            DocumentService.delete(db, process.id, type_code)
        return render_titulatec(request, "titulatec/partials/document_slot.html", _slot_ctx(dtype, None))
    finally:
        db.close()


def _programs(db):
    from itcj2.core.models.program import Program
    return [{"id": p.id, "name": p.name} for p in db.query(Program).order_by(Program.name).all()]


@router.get("/formato-b", name="titulatec.pages.student.formato_b")
async def formato_b(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.format_b.page.fill"])),
):
    """Shell del Formato B multi-step (arranca en el paso 1)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.format_b_service import FormatBService

    db = SessionLocal()
    try:
        process = DocumentService.get_active_process(db, int(user["sub"]))
        ctx = {"process": process.to_dict() if process else None}
        if process:
            fb = FormatBService.get_or_create(db, process)
            ctx.update({"step": 1, "datos": FormatBService.to_ctx(fb), "programs": _programs(db)})
    finally:
        db.close()
    return render_titulatec(request, "titulatec/student/formato_b.html", ctx)


@router.get("/formato-b/step/{n}", name="titulatec.pages.student.formato_b_step")
async def formato_b_step(
    n: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.format_b.page.fill"])),
):
    """Devuelve el parcial de un paso (navegación atrás, HTMX)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.format_b_service import FormatBService
    from fastapi.responses import Response

    if n not in (1, 2, 3):
        return Response(status_code=404)
    db = SessionLocal()
    try:
        process = DocumentService.get_active_process(db, int(user["sub"]))
        if not process:
            return Response(status_code=409)
        fb = FormatBService.get_or_create(db, process)
        ctx = {"step": n, "datos": FormatBService.to_ctx(fb), "programs": _programs(db)}
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/formato_b_step.html", ctx)


@router.post("/formato-b/step/{n}", name="titulatec.pages.student.formato_b_save")
async def formato_b_save(
    n: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.format_b.api.save"])),
):
    """Guarda el paso n y devuelve el parcial del siguiente (o 'done' al enviar)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.format_b_service import FormatBService
    from fastapi.responses import Response

    if n not in (1, 2, 3):
        return Response(status_code=404)
    form = dict(await request.form())
    db = SessionLocal()
    try:
        process = DocumentService.get_active_process(db, int(user["sub"]))
        if not process:
            return Response(status_code=409)
        fb = FormatBService.get_or_create(db, process)
        FormatBService.save_step(db, fb, n, form)

        if n < 3:
            ctx = {"step": n + 1, "datos": FormatBService.to_ctx(fb), "programs": _programs(db)}
        else:
            FormatBService.submit(db, fb)
            ctx = {"step": "done", "datos": FormatBService.to_ctx(fb), "programs": []}
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/formato_b_step.html", ctx)


# ===========================================================================
# Cita de cotejo (fase 2)
# ===========================================================================

_MONTHS_ES = ["", "ene", "feb", "mar", "abr", "may", "jun",
              "jul", "ago", "sep", "oct", "nov", "dic"]

# Checklist físico (fijo) que el alumno debe llevar a la cita de cotejo.
_COTEJO_CHECKLIST = [
    ("file-earmark-text", "Actas de nacimiento", "Original + copias."),
    ("card-text", "CURP certificada", "Impresión certificada (no la simple)."),
    ("shield-check", "e.Firma (SAT)", "Constancia de situación fiscal con e.Firma vigente."),
    ("clipboard-check", "Encuesta de egresados", "Comprobante de haberla contestado."),
    ("book", "No-adeudo de biblioteca", "Constancia de no adeudo vigente."),
    ("camera", "12 fotografías", "Tamaño credencial, ovaladas, B/N, fondo blanco, papel mate."),
    ("heart-pulse", "Vigencia de derechos IMSS", "Documento que acredite vigencia."),
    ("cash-coin", "$1,900 en efectivo", "Pago del proceso de titulación (efectivo)."),
]


def _cita_label(dt) -> str:
    if not dt:
        return "—"
    return f"{dt.day:02d} {_MONTHS_ES[dt.month]} {dt.year} · {dt:%H:%M}"


def _cita_card_ctx(db, user_id: int) -> dict:
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    process = DocumentService.get_active_process(db, user_id)
    appt = AppointmentService.get_for_process(db, process.id) if process else None
    appt_ctx = None
    if appt:
        appt_ctx = {
            "scheduled_label": _cita_label(appt.scheduled_at),
            "location": appt.location,
            "status": appt.status,
            "confirmed": appt.confirmed_at is not None,
            "change_requested": AppointmentService.has_change_request(appt),
        }
    return {
        "process": process.to_dict() if process else None,
        "appt": appt_ctx,
    }


@router.get("/cita", name="titulatec.pages.student.cita")
async def cita(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.page.my"])),
):
    """Página de la cita de cotejo del alumno: estado + checklist físico."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _cita_card_ctx(db, int(user["sub"]))
        ctx["checklist"] = _COTEJO_CHECKLIST
    finally:
        db.close()
    return render_titulatec(request, "titulatec/student/cita.html", ctx)


@router.post("/cita/confirmar", name="titulatec.pages.student.cita_confirm")
async def cita_confirm(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.api.confirm.own"])),
):
    """El alumno confirma asistencia. Devuelve la tarjeta re-renderizada (HTMX)."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    db = SessionLocal()
    try:
        process = DocumentService.get_active_process(db, int(user["sub"]))
        appt = AppointmentService.get_for_process(db, process.id) if process else None
        if appt and appt.status in ("scheduled",):
            AppointmentService.confirm(db, appt, int(user["sub"]))
        return render_titulatec(request, "titulatec/partials/cita_card.html",
                                _cita_card_ctx(db, int(user["sub"])))
    finally:
        db.close()


@router.post("/cita/solicitar-cambio", name="titulatec.pages.student.cita_request_change")
async def cita_request_change(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.api.confirm.own"])),
):
    """El alumno solicita un cambio de cita (el encargado decide). Devuelve la tarjeta."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    form = dict(await request.form())
    reason = form.get("reason", "")
    db = SessionLocal()
    try:
        process = DocumentService.get_active_process(db, int(user["sub"]))
        appt = AppointmentService.get_for_process(db, process.id) if process else None
        if appt:
            AppointmentService.request_change(db, appt, int(user["sub"]), reason)
        return render_titulatec(request, "titulatec/partials/cita_card.html",
                                _cita_card_ctx(db, int(user["sub"])))
    finally:
        db.close()


@router.post("/phase/1/submit", name="titulatec.pages.student.submit_initial_docs")
async def submit_initial_docs(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.process.api.advance"])),
):
    """Marca la fase 1 como 'en revisión' si los 3 documentos están subidos."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import ProcessPhase, Document
    from itcj2.apps.titulatec.services.document_service import DocumentService

    db = SessionLocal()
    try:
        process = DocumentService.get_active_process(db, int(user["sub"]))
        if not process:
            return Response(status_code=409)
        count = db.query(Document).filter(
            Document.process_id == process.id,
            Document.type_code.in_(_INITIAL_DOC_TYPES),
        ).count()
        if count < len(_INITIAL_DOC_TYPES):
            return Response(status_code=400, headers={"X-Tt-Error": "Faltan documentos por subir."})

        phase = db.query(ProcessPhase).filter_by(process_id=process.id, phase_number=1).first()
        if not phase:
            phase = ProcessPhase(process_id=process.id, phase_number=1)
            db.add(phase)
        phase.status = "in_review"
        db.commit()
        return Response(status_code=204)
    finally:
        db.close()
