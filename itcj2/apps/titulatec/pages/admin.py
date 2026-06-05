"""Páginas administrativas de TitulaTec (desktop, bandeja tipo email)."""
import logging
import secrets

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec, get_titulatec_roles
from itcj2.core.utils.security import hash_nip

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


def _month_arg(raw: str):
    """'YYYY-MM' → (year, month); default mes actual."""
    from datetime import date as date_cls, datetime
    try:
        d = datetime.strptime(raw, "%Y-%m") if raw else None
    except ValueError:
        d = None
    if d:
        return d.year, d.month
    today = date_cls.today()
    return today.year, today.month


def _cohort_summary_ctx(db, cohort) -> dict:
    from itcj2.apps.titulatec.models import TitulationProcess, ReviewAppointment, PhaseDefinition
    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
    procs = db.query(TitulationProcess).filter_by(cohort_id=cohort.id).all()
    by_phase = {}
    for p in procs:
        by_phase[p.current_phase] = by_phase.get(p.current_phase, 0) + 1
    phase_defs = (db.query(PhaseDefinition).filter_by(is_active=True)
                  .order_by(PhaseDefinition.order_index).all())
    defs = {d.number: d.name for d in db.query(PhaseDefinition).all()}
    max_phase = max((ph.number for ph in phase_defs), default=0) or 1
    # Funnel: una franja por fase activa (incluye fases con 0 para ver el flujo completo).
    phase_rows = [{"number": ph.number, "name": ph.name, "count": by_phase.get(ph.number, 0)}
                  for ph in phase_defs]
    total = len(procs)
    completed = sum(1 for p in procs if p.status == "completed")
    proc_ids = [p.id for p in procs]
    with_appt = 0
    if proc_ids:
        with_appt = (db.query(ReviewAppointment.process_id)
                     .filter(ReviewAppointment.process_id.in_(proc_ids)).distinct().count())
    try:
        review_days = len(ReviewDayService.list_days(db, cohort.id))
    except Exception:
        review_days = 0
    return {
        "period_code": cohort.period_code, "status": cohort.status,
        "opens_at": cohort.opens_at.isoformat() if cohort.opens_at else None,
        "closes_at": cohort.closes_at.isoformat() if cohort.closes_at else None,
        "total": total, "phase_rows": phase_rows, "with_appt": with_appt,
        "completed": completed,
        "pct_completed": round(completed / total * 100) if total else 0,
        "review_days": review_days, "max_phase": max_phase,
    }


_STUDENTS_PER_PAGE = 25


def _students_ctx(db, cohort_id, *, q, phase, page):
    from itcj2.core.models.user import User
    from itcj2.core.models.program import Program
    from itcj2.apps.titulatec.models import TitulationProcess, PhaseDefinition
    page = max(1, page or 1)
    base = (db.query(TitulationProcess, User)
            .join(User, User.id == TitulationProcess.student_id)
            .filter(TitulationProcess.cohort_id == cohort_id))
    if q:
        like = f"%{q.strip()}%"
        base = base.filter((User.control_number.ilike(like)) | (User.full_name.ilike(like)))
    if phase is not None:
        base = base.filter(TitulationProcess.current_phase == phase)
    total = base.count()
    total_pages = max(1, (total + _STUDENTS_PER_PAGE - 1) // _STUDENTS_PER_PAGE)
    page = min(page, total_pages)
    rows_q = (base.order_by(TitulationProcess.created_at.desc())
              .offset((page - 1) * _STUDENTS_PER_PAGE).limit(_STUDENTS_PER_PAGE).all())
    defs = {d.number: d.name for d in db.query(PhaseDefinition).all()}
    prog_names = {p.id: p.name for p in db.query(Program).all()}
    rows = [{
        "process_id": pr.id, "folio": pr.folio, "student": u.full_name,
        "control": u.control_number or "—",
        "program": prog_names.get(pr.program_id, "—"),
        "phase": pr.current_phase, "phase_name": defs.get(pr.current_phase, ""),
        "status": pr.status,
    } for pr, u in rows_q]
    return {"cohort_id": cohort_id, "rows": rows, "total": total, "page": page,
            "total_pages": total_pages, "q": q or "", "phase": phase if phase is not None else "",
            "programs": _programs(db), "modalities": _modalities(db)}


def _add_student(db, cohort, *, control, full_name, email, program_id, modality_id):
    """Crea/adjunta un alumno a la convocatoria. Si es nuevo, le pone password=control."""
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.services.import_service import ImportService
    existed = db.query(User).filter_by(control_number=control).first()
    ImportService.import_rows(db, cohort, [{
        "control_number": control, "full_name": full_name, "email": email,
        "program_id": program_id, "modality_id": modality_id,
    }])
    if not existed:
        user = db.query(User).filter_by(control_number=control).first()
        if user:
            user.password_hash = hash_nip(control)
            user.must_change_password = True
            db.commit()


def _review_days_ctx(db, cohort_id: int, year: int, month: int) -> dict:
    import calendar as _cal
    from datetime import date as date_cls, timedelta
    from itcj2.apps.titulatec.models import Cohort
    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
    cohort = db.get(Cohort, cohort_id)
    allowed = set(ReviewDayService.list_days(db, cohort_id))
    matrix = _cal.Calendar(firstweekday=0).monthdatescalendar(year, month)
    weeks = []
    for wk in matrix:
        cells = []
        for d in wk:
            cells.append({"date": d.isoformat(), "day": d.day,
                          "in_month": d.month == month, "on": d in allowed})
        weeks.append(cells)
    prev_m = date_cls(year, month, 1) - timedelta(days=1)
    next_first = (date_cls(year, month, 28) + timedelta(days=7)).replace(day=1)
    return {
        "cohort": cohort.to_dict() if cohort else None,
        "cohort_id": cohort_id,
        "year": year, "month": month,
        "month_label": f"{_cal.month_name[month]} {year}",
        "weeks": weeks,
        "weekdays": ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"],
        "prev_month": f"{prev_m.year}-{prev_m.month:02d}",
        "next_month": f"{next_first.year}-{next_first.month:02d}",
        "count": len(allowed),
    }


@router.get("/cohorts/{cohort_id}/students", name="titulatec.pages.admin.cohort_students")
async def cohort_students(
    cohort_id: int,
    request: Request,
    q: str = "",
    phase: str = "",
    page: int = 1,
    user: dict = Depends(require_page_app("titulatec", perms=_COHORT_PERMS)),
):
    from itcj2.database import SessionLocal
    ph = int(phase) if phase.strip().isdigit() else None
    db = SessionLocal()
    try:
        ctx = _students_ctx(db, cohort_id, q=q, phase=ph, page=page)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/cohort_students_table.html", ctx)


@router.get("/cohorts/{cohort_id}/students/lookup", name="titulatec.pages.admin.student_lookup")
async def student_lookup(cohort_id: int, request: Request, control: str = "",
                         user: dict = Depends(require_page_app("titulatec", perms=_COHORT_PERMS))):
    from itcj2.database import SessionLocal
    from itcj2.core.models.user import User
    db = SessionLocal()
    try:
        found = db.query(User).filter_by(control_number=control.strip()).first() if control.strip() else None
        ctx = {"cohort_id": cohort_id, "control": control.strip(),
               "found": ({"name": found.full_name} if found else None),
               "searched": bool(control.strip()),
               "programs": _programs(db), "modalities": _modalities(db)}
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/cohort_student_addform.html", ctx)


@router.get("/cohorts/{cohort_id}/students/cancel", name="titulatec.pages.admin.student_add_cancel")
async def student_add_cancel(cohort_id: int, request: Request,
                            user: dict = Depends(require_page_app("titulatec", perms=_COHORT_PERMS))):
    """Restaura el botón colapsado del alta manual (#student-add)."""
    return render_titulatec(request, "titulatec/partials/cohort_student_addbtn.html", {"cohort_id": cohort_id})


@router.post("/cohorts/{cohort_id}/students", name="titulatec.pages.admin.student_add")
async def student_add(cohort_id: int, request: Request,
                      user: dict = Depends(require_page_app("titulatec", perms=["titulatec.cohort.api.import_csv"]))):
    from fastapi.responses import Response
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import Cohort
    from itcj2.core.models.user import User
    form = dict(await request.form())
    control = (form.get("control_number") or "").strip()
    db = SessionLocal()
    try:
        cohort = db.get(Cohort, cohort_id)
        if not cohort or not control:
            return Response(status_code=400, headers={"X-Tt-Error": "Falta el número de control."})
        existed = db.query(User).filter_by(control_number=control).first()
        full_name = (form.get("full_name") or (existed.full_name if existed else "")).strip()
        if not full_name:
            return Response(status_code=400, headers={"X-Tt-Error": "Falta el nombre del alumno."})
        program_id = int(form["program_id"]) if form.get("program_id") else None
        modality_id = int(form["modality_id"]) if form.get("modality_id") else None
        _add_student(db, cohort, control=control, full_name=full_name, email=(form.get("email") or None),
                     program_id=program_id, modality_id=modality_id)
        ctx = _students_ctx(db, cohort_id, q="", phase=None, page=1)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/cohort_students.html", ctx)


@router.get("/cohorts/{cohort_id}/review-days", name="titulatec.pages.admin.review_days")
async def review_days(cohort_id: int, request: Request, month: str = "",
                      user: dict = Depends(require_page_app("titulatec", perms=["titulatec.cohort.api.review_days"]))):
    from itcj2.database import SessionLocal
    y, m = _month_arg(month)
    db = SessionLocal()
    try:
        ctx = _review_days_ctx(db, cohort_id, y, m)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/cohort_review_days.html", ctx)


@router.post("/cohorts/{cohort_id}/review-days/toggle", name="titulatec.pages.admin.review_days_toggle")
async def review_days_toggle(cohort_id: int, request: Request,
                             user: dict = Depends(require_page_app("titulatec", perms=["titulatec.cohort.api.review_days"]))):
    from datetime import datetime
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
    form = dict(await request.form())
    month = form.get("month") or ""
    try:
        day = datetime.strptime(form.get("date", ""), "%Y-%m-%d").date()
    except ValueError:
        day = None
    y, m = _month_arg(month)
    db = SessionLocal()
    try:
        if day:
            ReviewDayService.toggle(db, cohort_id, day, int(user["sub"]))
        ctx = _review_days_ctx(db, cohort_id, y, m)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/cohort_review_days.html", ctx)


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
        kpis = {
            "total": len(rows),
            "open": sum(1 for r in rows if r["status"] == "open"),
            "students": sum(r["processes"] for r in rows),
        }
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/cohorts.html", {
        "cohorts": rows, "periods": periods, "kpis": kpis,
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


@router.get("/cohorts/{cohort_id}", name="titulatec.pages.admin.cohort_detail")
async def cohort_detail(cohort_id: int, request: Request, tab: str = "resumen",
                        user: dict = Depends(require_page_app("titulatec", perms=_COHORT_PERMS))):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import Cohort
    from itcj2.core.services.authz_service import get_user_permissions_for_app
    tab = tab if tab in ("resumen", "dias", "alumnos", "importar") else "resumen"
    db = SessionLocal()
    try:
        cohort = db.get(Cohort, cohort_id)
        if not cohort:
            return Response(status_code=404)
        perms = get_user_permissions_for_app(db, int(user["sub"]), "titulatec")
        ctx = {"cohort": cohort.to_dict(), "cohort_id": cohort_id, "tab": tab,
               "can_edit_days": "titulatec.cohort.api.review_days" in perms}
        if tab == "resumen":
            ctx["summary"] = _cohort_summary_ctx(db, cohort)
        elif tab == "importar":
            pass  # el wizard de importación se sirve con el cohort ya en ctx
        elif tab == "dias":
            from datetime import date as _d
            today = _d.today()
            ctx["days"] = _review_days_ctx(db, cohort_id, today.year, today.month)
        elif tab == "alumnos":
            ctx.update(_students_ctx(db, cohort_id, q="", phase=None, page=1))
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/cohort_detail.html", ctx)


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
    view: str = "table",
    stuck: int = 0,
    user: dict = Depends(require_page_app("titulatec", perms=_PROCESS_VIEW_PERMS)),
):
    """Bandeja de procesos (tabla densa o tablero kanban) con KPIs, funnel de
    fases y señal de atoro (días sin moverse)."""
    from datetime import datetime
    from itcj2.config import get_settings
    from itcj2.database import SessionLocal
    from itcj2.core.models.user import User
    from itcj2.core.models.program import Program
    from itcj2.apps.titulatec.models import (
        TitulationProcess, PhaseDefinition, ProcessPhase, Modality,
    )
    from itcj2.apps.titulatec.services.scope_service import officer_programs

    view = "table" if view != "board" else "board"
    settings = get_settings()
    warn_days = settings.TITULATEC_IDLE_WARN_DAYS
    crit_days = settings.TITULATEC_IDLE_CRIT_DAYS

    def _empty(extra=None):
        ctx = {
            "rows": [], "status": status, "view": view, "stuck": stuck, "columns": [],
            "kpis": {"total": 0, "active": 0, "completed": 0, "on_hold": 0,
                     "cancelled": 0, "pct_completed": 0, "n_stuck": 0},
            "idle_warn": warn_days, "idle_crit": crit_days,
        }
        if extra:
            ctx.update(extra)
        return ctx

    db = SessionLocal()
    try:
        scope = officer_programs(db, int(user["sub"]))
        q = db.query(TitulationProcess)
        if scope != "ALL":
            if not scope:
                return render_titulatec(request, "titulatec/admin/processes.html", _empty())
            q = q.filter(TitulationProcess.program_id.in_(scope))
        if status:
            q = q.filter_by(status=status)

        procs = q.order_by(TitulationProcess.created_at.desc()).all()

        # KPIs sobre el universo filtrado por status/scope (antes del filtro stuck).
        kpis = {"total": len(procs), "active": 0, "completed": 0,
                "on_hold": 0, "cancelled": 0, "pct_completed": 0, "n_stuck": 0}
        for p in procs:
            if p.status in kpis:
                kpis[p.status] += 1
        if kpis["total"]:
            kpis["pct_completed"] = round(kpis["completed"] / kpis["total"] * 100)

        # Definiciones de fase + progreso.
        phase_defs = (db.query(PhaseDefinition)
                      .filter_by(is_active=True)
                      .order_by(PhaseDefinition.order_index).all())
        defs = {d.number: d.name for d in db.query(PhaseDefinition).all()}
        max_phase = max((ph.number for ph in phase_defs), default=0) or 1

        # Idle: started_at de la fase ACTUAL de cada proceso, en una sola query.
        proc_ids = [p.id for p in procs]
        phase_started = {}
        if proc_ids:
            for ph in (db.query(ProcessPhase)
                       .filter(ProcessPhase.process_id.in_(proc_ids)).all()):
                phase_started[(ph.process_id, ph.phase_number)] = ph.started_at

        modalities = {m.id: m.name for m in db.query(Modality).all()}
        now = datetime.now()

        rows = []
        for p in procs:
            u = db.get(User, p.student_id)
            prog = db.get(Program, p.program_id) if p.program_id else None
            since = phase_started.get((p.id, p.current_phase)) or p.updated_at
            idle_days = max(0, (now - since).days) if since else 0
            idle_level = ("crit" if idle_days >= crit_days
                          else "warn" if idle_days >= warn_days else "ok")
            progress_pct = max(0, min(100, round(p.current_phase / max_phase * 100)))
            rows.append({
                "id": p.id, "folio": p.folio,
                "student": u.full_name if u else "—",
                "control": u.control_number if u else "—",
                "program": prog.name if prog else "—",
                "modality": modalities.get(p.modality_id, "—"),
                "phase": p.current_phase, "phase_name": defs.get(p.current_phase, ""),
                "status": p.status,
                "idle_days": idle_days, "idle_level": idle_level,
                "progress_pct": progress_pct,
            })

        kpis["n_stuck"] = sum(1 for r in rows if r["idle_level"] == "crit")

        if stuck:
            rows = [r for r in rows if r["idle_level"] == "crit"]

        # Columnas del kanban: agrupar por fase actual.
        buckets = {ph.number: [] for ph in phase_defs}
        for r in rows:
            buckets.setdefault(r["phase"], []).append(r)
        columns = []
        for ph in phase_defs:
            cards = buckets.get(ph.number, [])
            columns.append({
                "number": ph.number, "name": ph.name, "cards": cards,
                "count": len(cards),
                "n_stuck": sum(1 for c in cards if c["idle_level"] == "crit"),
            })
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/processes.html", {
        "rows": rows, "status": status, "view": view, "stuck": stuck,
        "columns": columns, "kpis": kpis,
        "idle_warn": warn_days, "idle_crit": crit_days,
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
