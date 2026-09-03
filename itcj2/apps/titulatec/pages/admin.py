"""Páginas administrativas de TitulaTec (desktop, bandeja tipo email)."""
import logging
import secrets

from fastapi import APIRouter, Depends, File, Form, Path, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec, get_titulatec_roles
from itcj2.core.utils.security import hash_nip

logger = logging.getLogger("itcj2.apps.titulatec.pages.admin")

router = APIRouter(prefix="/admin", tags=["titulatec-pages-admin"])

# Convocatorias: SOLO la jefatura de Servicios Escolares.
#
# OJO CON LA FORMA DE LA LISTA: `require_page_app` la evalúa como **OR**
# (`itcj2/dependencies.py:131` → `_perms_set & cached_perms(...)`), no como AND.
# Aquí figuraban además `dashboard.admin` y `dashboard.school_services`, y como
# el rol operativo tiene el segundo, los permisos `cohort.*` eran DECORATIVOS:
# un encargado de carrera entraba a la lista, al detalle y al asistente de
# importación (medido con su JWT: 200 en `/cohorts`, `/cohorts/{id}` y
# `/cohorts/{id}/import`) aunque el DML no le concediera nada de cohort.
#
# Por eso quitarle los permisos en el DML no basta y hay que dejar aquí SOLO el
# permiso específico: cualquier `dashboard.*` que se vuelva a colar reabre el
# agujero en silencio, porque basta con que UNO de la lista coincida.
_COHORT_PERMS = ["titulatec.cohort.page.list"]

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


def _add_student(db, cohort, *, control, full_name, email, program_id, modality_id,
                 actor_id=None):
    """Crea/adjunta un alumno a la convocatoria. Si es nuevo, le pone password=control."""
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.services.import_service import ImportService
    existed = db.query(User).filter_by(control_number=control).first()
    ImportService.import_rows(db, cohort, [{
        "control_number": control, "full_name": full_name, "email": email,
        "program_id": program_id, "modality_id": modality_id,
    }], actor_id=actor_id, source="manual")
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
            return Response(status_code=400, headers={"X-Tt-Error": _hdr("Falta el número de control.")})
        existed = db.query(User).filter_by(control_number=control).first()
        full_name = (form.get("full_name") or (existed.full_name if existed else "")).strip()
        if not full_name:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr("Falta el nombre del alumno.")})
        program_id = int(form["program_id"]) if form.get("program_id") else None
        modality_id = int(form["modality_id"]) if form.get("modality_id") else None
        _add_student(db, cohort, control=control, full_name=full_name, email=(form.get("email") or None),
                     program_id=program_id, modality_id=modality_id, actor_id=int(user["sub"]))
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

def _preview_ctx(db, cohort_id, token, headers, mapping, rows, *,
                 overrides=None, excluded=None):
    from itcj2.apps.titulatec.services.import_service import ImportService, TARGET_FIELDS
    preview = ImportService.build_preview(db, rows, mapping,
                                          overrides=overrides, excluded=excluded)
    importable = sum(1 for r in preview if r["status"] != "error")
    return {
        "cohort_id": cohort_id, "token": token, "headers": headers,
        "mapping": mapping, "fields": TARGET_FIELDS, "preview": preview,
        "programs": _programs(db), "modalities": _modalities(db),
        "total": len(preview), "importable": importable,
        "warnings": sum(1 for r in preview if r["status"] == "warning"),
        "errors": sum(1 for r in preview if r["status"] == "error"),
        # Estado editable del wizard, re-emitido tal cual en dos campos ocultos:
        # el navegador NO reenvía las filas (ver `import_preview.html`).
        "excluded_value": ",".join(str(r["idx"]) for r in preview if not r["include"]),
        "overrides_value": _overrides_json(preview),
    }


def _overrides_json(preview) -> str:
    """Re-serializa las celdas que difieren del CSV, para el campo oculto.

    Sin esto una corrección manual se perdería en cuanto el admin cambiara un
    select de mapeo: el servidor reconstruye el preview desde el CSV en cada
    revalidación, y lo editado solo sobrevive si vuelve a viajar.
    """
    import json as _json
    out = {}
    for r in preview:
        diff = {k: r[k] for k in ("control_number", "full_name", "email",
                                  "program_id", "modality_id")
                if r[k] != r["base"][k]}
        if diff:
            out[str(r["idx"])] = diff
    return _json.dumps(out, ensure_ascii=False) if out else ""


def _wizard_state(form):
    """(token, mapping, overrides, excluded) del formulario del wizard.

    Son ~8 campos pase lo que pase: el preview no viaja de vuelta. Con 6 inputs
    por fila, un CSV de 166 filas ya superaba el `max_fields=1000` de Starlette
    y `await request.form()` levantaba `MultiPartException` → 400.
    """
    from itcj2.apps.titulatec.services.import_service import ImportService, TARGET_FIELDS
    token = form.get("token", "")
    mapping = {f: form.get(f"map_{f}", "") for f in TARGET_FIELDS}
    overrides = ImportService.parse_overrides(form.get("overrides"))
    # `None` (campo ausente) ≠ "" (nada desmarcado): sin el campo se aplica el
    # default de la primera carga, que excluye las filas con error.
    excluded = (ImportService.parse_excluded(form.get("excluded"))
                if "excluded" in form else None)
    return token, mapping, overrides, excluded


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
    from itcj2.apps.titulatec.services.import_service import ImportService

    form = dict(await request.form())
    token, mapping, overrides, excluded = _wizard_state(form)
    raw = ImportService.read_temp(token)
    if not raw:
        return Response(status_code=409)
    headers, rows = ImportService.parse(raw)

    db = SessionLocal()
    try:
        ctx = _preview_ctx(db, cohort_id, token, headers, mapping, rows,
                           overrides=overrides, excluded=excluded)
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
    from itcj2.apps.titulatec.services.import_service import ImportService

    form = dict(await request.form())
    token, mapping, overrides, excluded = _wizard_state(form)

    # Las filas NO vienen del formulario: se releen del CSV temporal y se les
    # aplica el mapeo + lo que el admin corrigió/desmarcó. Reenviar el preview
    # entero (6 inputs por fila) topaba con el `max_fields=1000` de Starlette a
    # partir de la fila 166, y una convocatoria real son cientos de alumnos.
    raw = ImportService.read_temp(token)
    if not raw:
        return Response(status_code=409)
    _headers, csv_rows = ImportService.parse(raw)

    db = SessionLocal()
    try:
        cohort = db.get(Cohort, cohort_id)
        if not cohort:
            return Response(status_code=404)
        preview = ImportService.build_preview(db, csv_rows, mapping,
                                              overrides=overrides, excluded=excluded)
        # guarda el mapeo usado para reusarlo la próxima vez
        ImportService.save_mapping(mapping)
        summary = ImportService.import_rows(db, cohort,
                                            ImportService.rows_to_import(preview),
                                            actor_id=int(user["sub"]), source="csv")
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

# Cómo se lee cada suceso del expediente. La voz es la del PERSONAL, no la del
# alumno: en `pages/student.py` el mismo evento dice «Confirmaste tu asistencia»
# y aquí «El alumno confirmó». Un evento sin entrada aquí se pinta con su código
# crudo en vez de desaparecer: un historial que se calla no es un historial.
_EVENT_UI = {
    "process_created":              ("Alta en la convocatoria",   "person-plus",            "neutral"),
    "document_uploaded":            ("Subió un documento",        "cloud-arrow-up",         "neutral"),
    "document_approved":            ("Documento aprobado",        "check-lg",               "success"),
    "document_rejected":            ("Documento rechazado",       "x-lg",                   "danger"),
    "document_deleted":             ("Documento eliminado",       "trash",                  "danger"),
    "phase_approved":               ("Fase aprobada",             "check-circle",           "success"),
    "phase_rejected":               ("Fase rechazada",            "exclamation-triangle",   "danger"),
    "process_completed":            ("Proceso completado",        "trophy",                 "success"),
    "appointment_scheduled":        ("Cita agendada",             "calendar-plus",          "neutral"),
    "appointment_confirmed":        ("El alumno confirmó",        "check2-circle",          "success"),
    "appointment_rescheduled":      ("Cita reagendada",           "arrow-repeat",           "amber"),
    "appointment_change_requested": ("El alumno pidió otro día",  "chat-left-dots",         "amber"),
    "appointment_in_progress":      ("Cotejo iniciado",           "play-circle",            "neutral"),
    "appointment_attended":         ("Cotejo atendido",           "check-circle",           "success"),
    "appointment_no_show":          ("No se presentó",            "person-x",               "danger"),
    "appointment_undo_no_show":     ("Se deshizo la falta",       "arrow-counterclockwise", "amber"),
}

# Fases con contenido propio en el expediente. El resto tiene modelo y tabla y
# nada más (sinodales, anexo, entrega final, ceremonia): se pintan diciéndolo,
# porque un panel vacío se lee como «no ha pasado nada» y no como «esto todavía
# no existe en la app».
_FASES_CON_PANEL = (0, 1, 2, 3)

_MESES = ["", "ene", "feb", "mar", "abr", "may", "jun",
          "jul", "ago", "sep", "oct", "nov", "dic"]

# Etiqueta del botón Regresar, por prefijo de ruta.
_BACK_LABELS = (
    ("/titulatec/admin/documents", "Documentos"),
    ("/titulatec/admin/appointments", "Citas de cotejo"),
    ("/titulatec/admin/cohorts", "Convocatoria"),
    ("/titulatec/admin/processes", "Procesos"),
)
_BACK_DEFAULT = "/titulatec/admin/processes"


def _hdr(msg: str) -> str:
    """Codifica un mensaje para que quepa en un header HTTP.

    Gemelo del de `pages/appointments.py`. Los valores de header son latin-1 por
    especificación y Starlette los codifica así: un mensaje con acentos —o sea,
    todos los nuestros— llega al cliente como bytes que no son UTF-8 válidos y
    revienta al decodificarlos. `titulatec-utils.js` lo decodifica al mostrarlo.

    En este módulo llevaba puesto desde siempre («Falta el número de control»);
    no había saltado porque ninguna prueba llegaba a esas ramas.
    """
    from urllib.parse import quote
    return quote(msg or "", safe="")


def _fecha_larga(dt) -> str:
    """`3 sep 2026 · 14:05`. Sin año no se distingue una convocatoria de otra."""
    if not dt:
        return ""
    return f"{dt.day} {_MESES[dt.month]} {dt.year} · {dt:%H:%M}"


def _back_ctx(raw: str | None) -> dict:
    """Valida el `?from=` y devuelve a dónde vuelve el botón Regresar.

    `from` llega del cliente y acaba dentro de un `href`, así que sin validar
    esto es un redirector abierto con la marca de la escuela: bastaría un enlace
    `…/processes/7?from=https://…` para que el salto saliera de un dominio de
    confianza. Tres cosas lo cierran:

      * tiene que empezar por `/titulatec/admin/` — descarta esquemas
        (`javascript:`, `https:`) y el resto de apps del ITCJ;
      * no puede empezar por `//` — el navegador lee `//host/x` como URL
        externa aunque parezca una ruta;
      * no puede traer `..` ni barra invertida — normalizaciones que se salen
        del prefijo.

    Lo que no pasa cae a Procesos, que es de donde se llegaba históricamente.
    """
    url = (raw or "").strip()
    valido = (
        url.startswith("/titulatec/admin/")
        and not url.startswith("//")
        and ".." not in url
        and "\\" not in url
    )
    if not valido:
        url = _BACK_DEFAULT
    ruta = url.split("?", 1)[0]
    etiqueta = next((lab for pre, lab in _BACK_LABELS if ruta.startswith(pre)), "Procesos")
    return {"url": url, "label": etiqueta}


def _evento_detalle(ev, doc_names: dict) -> str | None:
    """La línea de abajo del suceso: lo que el payload sepa contar.

    Es lo que separa «Documento rechazado» de «Documento rechazado · CURP
    certificada — Falta el sello». Un payload viejo o incompleto no rompe: cada
    trozo se añade solo si está.
    """
    p = ev.payload or {}
    partes = []
    code = p.get("type_code")
    if code:
        partes.append(doc_names.get(code, code))
    if p.get("version"):
        partes.append(f"v{p['version']}")
    if p.get("scheduled_at"):
        partes.append(str(p["scheduled_at"]).replace("T", " ")[:16])
    if p.get("source"):
        partes.append("importación CSV" if p["source"] == "csv" else "alta manual")
    texto = " · ".join(partes)
    motivo = p.get("note") or p.get("reason")
    if motivo:
        texto = f"{texto} — {motivo}" if texto else str(motivo)
    return texto or None


def _detail_ctx(db, process_id: int, *, open_phase=None, back_raw=None,
                doc_abierto=None) -> dict | None:
    """El expediente completo en un número FIJO de consultas.

    Antes esto pedía un `DocumentType` por cada código dentro de un bucle, y no
    leía un solo `ProcessEvent`: la página decía cómo estaba el proceso y no qué
    le había pasado. Ahora trae catálogo de fases, fases del proceso, documentos,
    tipos, eventos y los usuarios que los provocaron por lote, así que añadir el
    historial no multiplica el coste por fase.
    """
    from itcj2.core.models.user import User
    from itcj2.core.models.program import Program
    from itcj2.apps.titulatec.models import (
        TitulationProcess, Modality, Cohort, Document, DocumentType,
        PhaseDefinition, ProcessEvent, ProcessPhase, FormatB,
    )
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.format_b_service import FormatBService
    from itcj2.apps.titulatec.utils import storage

    proc = db.get(TitulationProcess, process_id)
    if not proc:
        return None
    student = db.get(User, proc.student_id)
    cohort = db.get(Cohort, proc.cohort_id)
    modality = db.get(Modality, proc.modality_id) if proc.modality_id else None
    program = db.get(Program, proc.program_id) if proc.program_id else None

    # ---- catálogos y filas del proceso, por lote ----
    pdefs = (db.query(PhaseDefinition).filter_by(is_active=True)
             .order_by(PhaseDefinition.order_index).all())
    fases_db = {ph.phase_number: ph for ph in
                db.query(ProcessPhase).filter_by(process_id=process_id).all()}
    # Sin `is_active`: si un tipo se desactiva, el documento ya subido tiene que
    # seguir mostrándose con su nombre y no con el código crudo.
    tipos = {t.code: t.name for t in db.query(DocumentType)
             .filter(DocumentType.code.in_(_INITIAL_DOC_TYPES)).all()}
    doc_names = {code: tipos.get(code, code) for code in _INITIAL_DOC_TYPES}
    docs_db = {d.type_code: d for d in db.query(Document)
               .filter(Document.process_id == process_id,
                       Document.type_code.in_(_INITIAL_DOC_TYPES)).all()}

    eventos = (db.query(ProcessEvent).filter_by(process_id=process_id)
               .order_by(ProcessEvent.created_at, ProcessEvent.id).all())
    actor_ids = {e.actor_id for e in eventos if e.actor_id}
    actor_ids |= {ph.reviewed_by_id for ph in fases_db.values() if ph.reviewed_by_id}
    actor_ids |= {d.reviewed_by_id for d in docs_db.values() if d.reviewed_by_id}
    actores = ({u.id: u.full_name for u in db.query(User).filter(User.id.in_(actor_ids)).all()}
               if actor_ids else {})

    # ---- documentos de la fase 1 (solo lectura) ----
    docs = []
    for code in _INITIAL_DOC_TYPES:
        doc = docs_db.get(code)
        # `missing` se resuelve EN EL SERVIDOR: un archivo que ya no está en
        # disco tiene que decirlo, no dejar un visor mudo.
        falta = True
        if doc:
            try:
                falta = not storage.abs_path(doc.file_path).exists()
            except Exception:
                falta = True
        docs.append({
            "type_code": code, "name": doc_names[code],
            "doc": ({"original_name": doc.original_name, "review_status": doc.review_status,
                     "size_bytes": doc.size_bytes or 0, "review_note": doc.review_note,
                     "version": doc.version or 1,
                     "reviewed_by": actores.get(doc.reviewed_by_id)} if doc else None),
            "missing": bool(doc) and falta,
            "view_url": f"/titulatec/admin/documents/{process_id}/document/{code}",
        })
    legibles = [d for d in docs if d["doc"] and not d["missing"]]
    abierto = next((d for d in legibles if d["type_code"] == doc_abierto),
                   legibles[0] if legibles else None)

    # ---- eventos repartidos por fase ----
    por_fase, sin_fase = {}, []
    for ev in eventos:
        etiqueta, icono, tono = _EVENT_UI.get(ev.event_type,
                                              (ev.event_type, "dot", "neutral"))
        fila = {"label": etiqueta, "icon": icono, "tone": tono,
                "when": _fecha_larga(ev.created_at),
                "actor": actores.get(ev.actor_id),
                "detail": _evento_detalle(ev, doc_names)}
        # Un evento sin fase no se cuelga de una arbitraria: va a su propio
        # bloque al final, que no se pinta si está vacío.
        if ev.phase_number is None:
            sin_fase.append(fila)
        else:
            por_fase.setdefault(ev.phase_number, []).append(fila)

    # ---- las 9 fases ----
    current = proc.current_phase
    max_phase = max((pd.number for pd in pdefs), default=0) or 1
    numeros = {pd.number for pd in pdefs}
    if open_phase is None or open_phase not in numeros:
        open_phase = current
    fases = []
    for pd in pdefs:
        ph = fases_db.get(pd.number)
        eventos_fase = por_fase.get(pd.number, [])
        fases.append({
            "number": pd.number, "code": pd.code, "name": pd.name,
            "status": ph.status if ph else "pending",
            "started": _fecha_larga(ph.started_at) if ph else "",
            "completed": _fecha_larga(ph.completed_at) if ph else "",
            "reviewed_by": actores.get(ph.reviewed_by_id) if ph else None,
            "rejection_reason": ph.rejection_reason if ph else None,
            "is_current": pd.number == current,
            "is_open": pd.number == open_phase,
            "is_done": ph is not None and ph.status == "approved",
            "tiene_panel": pd.number in _FASES_CON_PANEL,
            "events": eventos_fase,
            "n_events": len(eventos_fase),
        })

    fb_row = db.get(FormatB, process_id)
    formato_b = None
    if fb_row and fb_row.status != "draft":
        formato_b = {"status": fb_row.status, "datos": FormatBService.to_ctx(fb_row),
                     "program_name": program.name if program else None}

    appt = AppointmentService.get_for_process(db, process_id)
    return {
        "process": proc.to_dict(),
        "student": {
            "name": student.full_name if student else "—",
            "control": student.control_number if student else "—",
            "email": student.email if student else None,
        },
        "cohort_period": cohort.period_code if cohort else None,
        "cohort_id": proc.cohort_id,
        "program_name": program.name if program else None,
        "modality_name": modality.name if modality else None,
        "current_phase": current,
        "progress_pct": max(0, min(100, round(current / max_phase * 100))),
        "fases": fases,
        "open_phase": open_phase,
        "back": _back_ctx(back_raw),
        "docs": docs,
        "doc_abierto": abierto["type_code"] if abierto else None,
        "doc_src": abierto["view_url"] if abierto else None,
        "appt": ({"status": appt.status,
                  "scheduled_label": _fecha_larga(appt.scheduled_at),
                  "location": appt.location, "note": appt.note,
                  "change_request": appt.change_request,
                  "change_requested_at": _fecha_larga(appt.change_requested_at)}
                 if appt else None),
        "formato_b": formato_b,
        "otros_eventos": sin_fase,
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


def _exp_params(request) -> dict:
    """Los tres parámetros de zona del expediente, leídos del query string.

    Viajan igual en el GET de la página y en los POST de las acciones, porque el
    cuerpo que devuelven las acciones es la MISMA página: si no viajaran, aprobar
    una fase te devolvería al expediente sin el documento abierto y sin el
    botón Regresar apuntando a donde estabas.
    """
    qp = request.query_params
    crudo = qp.get("fase") or ""
    try:
        fase = int(crudo)
    except (TypeError, ValueError):
        fase = None
    return {"open_phase": fase, "back_raw": qp.get("from"), "doc_abierto": qp.get("doc")}


def _exp_query(params: dict) -> str:
    """Reconstruye el query string de zona para las URL de las acciones."""
    from urllib.parse import urlencode
    pares = []
    if params.get("open_phase") is not None:
        pares.append(("fase", params["open_phase"]))
    if params.get("doc_abierto"):
        pares.append(("doc", params["doc_abierto"]))
    if params.get("back_raw"):
        pares.append(("from", params["back_raw"]))
    return urlencode(pares)


@router.get("/processes/{process_id}", name="titulatec.pages.admin.process_detail")
async def process_detail(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=_PROCESS_VIEW_PERMS)),
):
    """El expediente del alumno: cabecera + acordeón de las 9 fases con su historial."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope
    db = SessionLocal()
    try:
        # 404 uniforme: "no existe" y "no es de tus carreras" son indistinguibles.
        # El guard ya cubre el proceso inexistente, asi que `_detail_ctx` no
        # puede devolver None a partir de aqui.
        assert_process_in_scope(db, int(user["sub"]), process_id)
        params = _exp_params(request)
        ctx = _detail_ctx(db, process_id, **params)
        ctx["zona"] = _exp_query(params)
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/process_detail.html", ctx)


def _render_detail_body(request, db, process_id):
    """El cuerpo del expediente re-renderizado tras una acción (swap HTMX)."""
    params = _exp_params(request)
    ctx = _detail_ctx(db, process_id, **params)
    ctx["zona"] = _exp_query(params)
    return render_titulatec(request, "titulatec/partials/processes/_exp_shell.html", ctx)


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
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    form = dict(await request.form())
    action = form.get("action")
    note = form.get("note")
    status = "approved" if action == "approve" else "rejected"
    db = SessionLocal()
    try:
        assert_process_in_scope(db, int(user["sub"]), process_id)
        fb = db.get(FormatB, process_id)
        if fb:
            FormatBService.review(db, fb, status=status, note=note, reviewer_id=int(user["sub"]))
        return _render_detail_body(request, db, process_id)
    finally:
        db.close()


@router.post("/processes/{process_id}/phase/{n}/approve", name="titulatec.pages.admin.phase_approve")
async def phase_approve(
    process_id: int,
    request: Request,
    n: int = Path(ge=0),
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.process.api.approve_phase"])),
):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    db = SessionLocal()
    try:
        # El guard sustituye al `db.get` + 404: devuelve el proceso ya cargado y
        # ademas comprueba que sea de una carrera del usuario.
        proc = assert_process_in_scope(db, int(user["sub"]), process_id)
        try:
            PhaseService.approve_phase(db, proc, n, int(user["sub"]))
        except ValueError as exc:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        return _render_detail_body(request, db, process_id)
    finally:
        db.close()


@router.post("/processes/{process_id}/phase/{n}/reject", name="titulatec.pages.admin.phase_reject")
async def phase_reject(
    process_id: int,
    request: Request,
    n: int = Path(ge=0),
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.process.api.reject_phase"])),
):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    form = dict(await request.form())
    reason = (form.get("reason") or "").strip()
    # Sin motivo, al alumno le llega «Fase rechazada» a secas en su panel y tiene
    # que venir a preguntar qué falta. La bandeja de Documentos ya lo exige desde
    # que existe (`pages/documents.py`); esto cierra el otro camino.
    if not reason:
        return Response(status_code=400, headers={
            "X-Tt-Error": _hdr("Escribe el motivo del rechazo: es lo que el alumno lee.")})
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, int(user["sub"]), process_id)
        try:
            PhaseService.reject_phase(db, proc, n, int(user["sub"]), reason)
        except ValueError as exc:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        return _render_detail_body(request, db, process_id)
    finally:
        db.close()
