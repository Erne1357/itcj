"""Agenda de Citas de cotejo (fase 2) — Servicios Escolares (desktop).

Página dedicada tipo bandeja: el encargado de la carrera ve su agenda, agenda
citas a los procesos que llegaron a fase 2, reagenda, marca "en proceso" (cotejo)
viendo los documentos que subió el alumno, y marca asistencia. La aprobación de la
fase 2 sigue siendo el botón genérico del detalle del proceso.

Patrón HTMX: un único cuerpo `#appt-body` (lista + detalle) que se re-renderiza en
cada acción, conservando el proceso seleccionado.
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.appointments")

router = APIRouter(prefix="/admin/appointments", tags=["titulatec-pages-appointments"])

_INITIAL_DOC_TYPES = ["birth_certificate", "high_school_cert", "curp"]

_MONTHS_ES = ["", "ene", "feb", "mar", "abr", "may", "jun",
              "jul", "ago", "sep", "oct", "nov", "dic"]

# Permisos para ver/gestionar la agenda (servicios escolares + admin).
_VIEW_PERMS = ["titulatec.appointment.page.list", "titulatec.dashboard.school_services",
               "titulatec.dashboard.admin"]


def _label(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return f"{dt.day:02d} {_MONTHS_ES[dt.month]} {dt.year} · {dt:%H:%M}"


def _input_value(dt: datetime | None) -> str:
    """Valor para <input type='datetime-local'>."""
    return dt.strftime("%Y-%m-%dT%H:%M") if dt else ""


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _to_int(raw) -> int | None:
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _programs(db):
    from itcj2.core.models.program import Program
    return [{"id": p.id, "name": p.name} for p in db.query(Program).order_by(Program.name).all()]


def _appt_dict(appt) -> dict | None:
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    if not appt:
        return None
    return {
        "id": appt.id,
        "scheduled_label": _label(appt.scheduled_at),
        "scheduled_input": _input_value(appt.scheduled_at),
        "location": appt.location,
        "status": appt.status,
        "confirmed": appt.confirmed_at is not None,
        "change_request": AppointmentService.change_request_text(appt),
    }


def _detail_ctx(db, process_id: int) -> dict | None:
    """Detalle de la cita de un proceso (panel derecho)."""
    from itcj2.core.models.user import User
    from itcj2.core.models.program import Program
    from itcj2.apps.titulatec.models import TitulationProcess, Modality, Cohort, DocumentType
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.document_service import DocumentService

    proc = db.get(TitulationProcess, process_id)
    if not proc:
        return None
    student = db.get(User, proc.student_id)
    program = db.get(Program, proc.program_id) if proc.program_id else None
    modality = db.get(Modality, proc.modality_id) if proc.modality_id else None
    cohort = db.get(Cohort, proc.cohort_id)

    docs = []
    for code in _INITIAL_DOC_TYPES:
        dt = db.query(DocumentType).filter_by(code=code).first()
        doc = DocumentService.get_document(db, process_id, code)
        docs.append({
            "type_code": code,
            "name": dt.name if dt else code,
            "doc": ({"original_name": doc.original_name, "review_status": doc.review_status,
                     "size_bytes": doc.size_bytes or 0} if doc else None),
            "view_url": f"/titulatec/admin/appointments/{process_id}/document/{code}",
        })

    appt = AppointmentService.get_for_process(db, process_id)
    return {
        "process": {"id": proc.id, "folio": proc.folio, "current_phase": proc.current_phase,
                    "status": proc.status},
        "student": {"name": student.full_name if student else "—",
                    "control": student.control_number if student else "—",
                    "email": student.email if student else None},
        "program_name": program.name if program else None,
        "modality_name": modality.name if modality else None,
        "cohort_period": cohort.period_code if cohort else None,
        "appt": _appt_dict(appt),
        "docs": docs,
    }


def _body_ctx(db, *, selected_id, program_id, status, mine, user_id) -> dict:
    from itcj2.core.models.user import User
    from itcj2.core.models.program import Program
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.scope_service import officer_programs

    scope = officer_programs(db, user_id)
    allowed = None if scope == "ALL" else scope

    appts = AppointmentService.list_appointments(
        db, program_id=program_id, status=status or None,
        owner_id=user_id if mine else None, allowed_program_ids=allowed)
    rows = []
    for a in appts:
        proc = a.process
        u = db.get(User, proc.student_id) if proc else None
        prog = db.get(Program, proc.program_id) if proc and proc.program_id else None
        rows.append({
            "process_id": a.process_id,
            "folio": proc.folio if proc else "—",
            "student": u.full_name if u else "—",
            "control": u.control_number if u else "—",
            "program": prog.name if prog else "—",
            "scheduled_label": _label(a.scheduled_at),
            "status": a.status,
            "change_request": AppointmentService.has_change_request(a),
        })

    pending = []
    for proc in AppointmentService.list_pending_processes(
            db, program_id=program_id, allowed_program_ids=allowed):
        u = db.get(User, proc.student_id)
        prog = db.get(Program, proc.program_id) if proc.program_id else None
        pending.append({
            "process_id": proc.id, "folio": proc.folio,
            "student": u.full_name if u else "—",
            "control": u.control_number if u else "—",
            "program": prog.name if prog else "—",
        })

    detail = _detail_ctx(db, selected_id) if selected_id else None
    return {
        "rows": rows, "pending": pending, "detail": detail,
        "selected_id": selected_id,
        "programs": _programs(db),
        "f_program": program_id or "", "f_status": status or "", "f_mine": mine,
    }


def _render_body(request, db, *, selected_id, program_id=None, status=None, mine=False, user_id=None):
    ctx = _body_ctx(db, selected_id=selected_id, program_id=program_id,
                    status=status, mine=mine, user_id=user_id)
    return render_titulatec(request, "titulatec/partials/appointments_body.html", ctx)


# ===========================================================================
# Páginas / parciales
# ===========================================================================

@router.get("", name="titulatec.pages.appointments.home")
async def home(
    request: Request,
    program_id: str = "",
    status: str = "",
    mine: int = 0,
    selected: str = "",
    user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS)),
):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, selected_id=_to_int(selected), program_id=_to_int(program_id),
                        status=status or None, mine=bool(mine), user_id=int(user["sub"]))
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/appointments.html", ctx)


@router.get("/body", name="titulatec.pages.appointments.body")
async def body(
    request: Request,
    program_id: str = "",
    status: str = "",
    mine: int = 0,
    selected: str = "",
    user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS)),
):
    """Cuerpo (lista + detalle) re-renderizado por filtros / selección (HTMX)."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        return _render_body(request, db, selected_id=_to_int(selected),
                            program_id=_to_int(program_id),
                            status=status or None, mine=bool(mine), user_id=int(user["sub"]))
    finally:
        db.close()


# ===========================================================================
# Acciones (re-renderizan el cuerpo, conservando el proceso seleccionado)
# ===========================================================================

@router.post("/{process_id}/schedule", name="titulatec.pages.appointments.schedule")
async def schedule(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.api.create"])),
):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    form = dict(await request.form())
    dt = _parse_dt(form.get("scheduled_at"))
    db = SessionLocal()
    try:
        if dt:
            AppointmentService.create(
                db, process_id, scheduled_at=dt, location=(form.get("location") or None),
                created_by_id=int(user["sub"]), note=(form.get("note") or None))
        return _render_body(request, db, selected_id=process_id, user_id=int(user["sub"]))
    finally:
        db.close()


@router.post("/{process_id}/reschedule", name="titulatec.pages.appointments.reschedule")
async def reschedule(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.api.reschedule"])),
):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    form = dict(await request.form())
    dt = _parse_dt(form.get("scheduled_at"))
    db = SessionLocal()
    try:
        appt = AppointmentService.get_for_process(db, process_id)
        if appt and dt:
            AppointmentService.reschedule(
                db, appt, scheduled_at=dt, location=(form.get("location") or None),
                actor_id=int(user["sub"]), note=(form.get("note") or None))
        return _render_body(request, db, selected_id=process_id, user_id=int(user["sub"]))
    finally:
        db.close()


@router.post("/{process_id}/start", name="titulatec.pages.appointments.start")
async def start(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.api.update"])),
):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    db = SessionLocal()
    try:
        appt = AppointmentService.get_for_process(db, process_id)
        if appt:
            AppointmentService.start(db, appt, int(user["sub"]))
        return _render_body(request, db, selected_id=process_id, user_id=int(user["sub"]))
    finally:
        db.close()


@router.post("/{process_id}/attended", name="titulatec.pages.appointments.attended")
async def attended(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.api.mark_attended"])),
):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    db = SessionLocal()
    try:
        appt = AppointmentService.get_for_process(db, process_id)
        if appt:
            AppointmentService.mark_attended(db, appt, int(user["sub"]))
        return _render_body(request, db, selected_id=process_id, user_id=int(user["sub"]))
    finally:
        db.close()


@router.post("/{process_id}/no-show", name="titulatec.pages.appointments.no_show")
async def no_show(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.api.update"])),
):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    db = SessionLocal()
    try:
        appt = AppointmentService.get_for_process(db, process_id)
        if appt:
            AppointmentService.mark_no_show(db, appt, int(user["sub"]))
        return _render_body(request, db, selected_id=process_id, user_id=int(user["sub"]))
    finally:
        db.close()


# ===========================================================================
# Ver documento subido por el alumno (para cotejo contra el físico)
# ===========================================================================

@router.get("/{process_id}/document/{type_code}", name="titulatec.pages.appointments.document")
async def document_file(
    process_id: int,
    type_code: str,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.document.api.read.all"])),
):
    """Sirve el archivo del documento (inline) para cotejarlo."""
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
