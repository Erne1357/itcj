"""Páginas administrativas de TitulaTec (desktop, bandeja tipo email)."""
import logging
import secrets
from datetime import datetime, time

from fastapi import APIRouter, Depends, File, Form, Path, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.utils.paging import PAGE_SIZE
from itcj2.apps.titulatec.pages.nav import render_titulatec, get_titulatec_roles
# Las guardas REALES de las pestañas a las que enlaza el expediente (ver
# `_TAB_PERMS`, abajo). Ninguno de estos tres módulos importa `admin`: no hay
# ciclo, y la misma lista (no una copia) sigue a la guarda si cambia.
from itcj2.apps.titulatec.pages.appointments import _VIEW_PERMS as _APPOINTMENTS_VIEW_PERMS
from itcj2.apps.titulatec.pages.documents import _VIEW_PERMS as _DOCUMENTS_VIEW_PERMS
from itcj2.apps.titulatec.pages.handoff_admin import _LIST as _HANDOFF_LIST_PERMS
from itcj2.core.utils.security import hash_nip
from starlette.concurrency import run_in_threadpool

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

# Vista COMPLETA del expediente (spec 2026-10-07 §7, D7): el acordeón con todo
# el desglose (documentos y visor, historial, cita, requisitos, biblioteca,
# encuesta, correos) y sus acciones. `process.api.read.all` NO está: es alcance
# de DATOS («ALL» en `officer_programs`), no una página. Revisado el 2026-10-07
# (DML 03 + 15 y la BD de dev, copia de prod): todo rol que hoy abre el
# expediente completo -admin, school_services, school_services_head y
# titulaciones- trae `process.page.detail` Y `process.page.list`; nadie
# dependía de `read.all` ni de un `dashboard.*` solos.
_PROCESS_FULL_VIEW_PERMS = [
    "titulatec.process.page.list", "titulatec.process.page.detail",
    "titulatec.dashboard.admin", "titulatec.dashboard.school_services", "titulatec.dashboard.titulaciones",
]
# Vista RESUMIDA (D7, D8): el Departamento de Titulación. Cabecera + fases
# ANTERIORES al corte a T-soft con nombre, estado y fecha; nada del desglose.
_PROCESS_SUMMARY_PERMS = ["titulatec.process.page.summary"]

# Guarda del EXPEDIENTE (`GET /processes/{id}`): completa ∪ resumida. Qué vista
# sale lo decide `_vista_completa`. También la usa `mail_admin._process_opener`
# («la MISMA regla que el expediente»); desde el 2026-10-07 ya NO es la guarda
# de la lista ni incluye `read.all`.
_PROCESS_VIEW_PERMS = _PROCESS_FULL_VIEW_PERMS + _PROCESS_SUMMARY_PERMS

# La LISTA de Procesos (`/processes`, spec 2026-10-07-titulatec-liberados-
# biblioteca-helpdesk-design.md §1.2): guarda propia, el MISMO código que revela
# la pestaña «Procesos» en `nav._ADMIN_NAV` (página abierta ⇔ pestaña visible).
# Compartía `_PROCESS_VIEW_PERMS` con el expediente, y con ese OR bastaba
# `process.page.detail` o un `dashboard.*` suelto para abrirla. Antes de cortarla
# se revisó quién entraba (DML 03 + 15 y la BD de dev, copia de prod, el
# 2026-10-07): admin, school_services, school_services_head, titulaciones y
# titulacion, los cinco CON `process.page.list`; nadie por detail/read.all/
# dashboard.* solos, ni por puesto (`core_position_app_perms`) ni directo
# (`core_user_app_perms`). Solo la pierde Titulación (D1), y por el DML.
_PROCESS_LIST_PERMS = ["titulatec.process.page.list"]

# Pestañas a las que el expediente enlaza o regresa -> la guarda REAL de la ruta
# destino. Un enlace que contesta 403 es peor que no estar (mismo criterio que
# `can_mark_reqs`): el expediente solo pinta los que el actor puede abrir, y el
# «Regresar» por omisión elige entre Procesos y Liberados con este mismo mapa.
_TAB_PERMS = {
    "processes": _PROCESS_LIST_PERMS,
    "liberados": _HANDOFF_LIST_PERMS,
    "cohorts": _COHORT_PERMS,
    "documents": _DOCUMENTS_VIEW_PERMS,
    "appointments": _APPOINTMENTS_VIEW_PERMS,
}


def _tabs_abiertas(perms) -> dict:
    """`{pestaña: bool}` con `perms & guarda` -- OR, igual que `require_page_app`.
    `perms` sale de `cached_perms` (la MISMA fuente que el gate)."""
    return {tab: bool(perms & set(need)) for tab, need in _TAB_PERMS.items()}


def _vista_completa(perms) -> bool:
    """¿El actor ve el expediente COMPLETO? (D7). Si no, el resumido."""
    return bool(perms & set(_PROCESS_FULL_VIEW_PERMS))


def _exigir_vista_completa(db, user_id: int) -> None:
    """Guarda de las ACCIONES del expediente (`/processes/{id}/...`): todas
    responden el expediente ENTERO re-renderizado (`_render_detail_body`), así
    que quien solo tiene el resumen no pasa, aunque su set conserve el permiso
    de la acción (Titulación guarda el dictamen dormido de las fases 3-8, D1).
    403 como el gate (`PageForbidden`), y ANTES de escribir nada. Va después de
    `assert_process_in_scope`, que `test_scope_guard.py` exige primero."""
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.exceptions import PageForbidden

    if not _vista_completa(cached_perms(db, user_id, "titulatec")):
        raise PageForbidden(has_app_access=True)


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


def _parse_day(raw: str | None):
    """'YYYY-MM-DD' → `date`, o `None`. Vacío y basura dan `None`, no 500."""
    from datetime import datetime
    if not raw or not str(raw).strip():
        return None
    try:
        return datetime.strptime(str(raw).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# Hora por omisión de cada extremo de la ventana cuando el formulario la deja
# vacía (spec 2026-09-27 D8/D9). El cierre es 23:59:59 —se lee «23:59»— para que
# quien envía a las 23:59:30 del último día siga dentro.
_OPENS_DEFAULT_TIME = time(0, 0)
_CLOSES_DEFAULT_TIME = time(23, 59, 59)


def _parse_window_dt(date_raw: str | None, time_raw: str | None, *,
                     default: time) -> datetime | None:
    """Fecha `YYYY-MM-DD` (obligatoria) + hora `HH:MM` (opcional) → `datetime`.

    Hora vacía → `default`. Fecha vacía o ilegible, u hora ilegible → `None`,
    nunca un 500: el panel de la ventana (`cohort_window`) lo convierte en
    400 «La apertura y el cierre son obligatorios.» y el alta de convocatoria
    (`cohort_create`) en un 303 a `?error=ventana`, sin crear nada. Una hora
    que no se entiende NO cae al valor por omisión: abrir a las 00:00 lo que
    la jefa quiso abrir a las 09:00 es peor que pedírsela otra vez.
    """
    d = _parse_day(date_raw)
    if d is None:
        return None
    t = (time_raw or "").strip()
    if not t:
        return datetime.combine(d, default)
    try:
        return datetime.combine(d, datetime.strptime(t, "%H:%M").time())
    except ValueError:
        return None


def _fecha_hora(dt) -> str:
    """'05/10/2026 09:00' para las cabeceras del panel. Solo dígitos, así que
    `strftime` no depende del locale del proceso."""
    return dt.strftime("%d/%m/%Y %H:%M")


def _window_ctx(db, cohort, *, can_edit: bool) -> dict:
    """Contexto del parcial `cohort/cohort_window.html`.

    `opens_date/opens_time/closes_date/closes_time` son el par fecha + hora por
    extremo, SIEMPRE precargado: `CohortService.set_window` escribe los dos
    extremos con lo que reciba, sin conservar lo anterior. La fecha va en ISO
    (`YYYY-MM-DD`) porque `<input type="date">` solo acepta ese formato —un ISO
    con hora lo deja en blanco—; la hora en `HH:MM`.

    La hora que coincide con la de omisión va VACÍA: el cierre por omisión es
    23:59:59 y un `<input type="time">` de minutos no puede llevar los
    segundos; precargado como «23:59», re-guardar la ventana sin tocarla
    movería el cierre a 23:59:00 y se perdería el último minuto. Vacío vuelve a
    ser 23:59:59 (`_parse_window_dt`), y el formulario lo dice («vacío = 23:59»).

    `opens_label/closes_label` son la lectura «dd/mm/aaaa hh:mm» de quien no
    puede editar (la misma que la cabecera del detalle).
    """
    def _hora(dt, default):
        return "" if dt.time() == default else dt.strftime("%H:%M")

    return {
        "cohort_id": cohort.id,
        "window": {
            "status": cohort.status,
            "opens_date": cohort.opens_at.date().isoformat(),
            "opens_time": _hora(cohort.opens_at, _OPENS_DEFAULT_TIME),
            "closes_date": cohort.closes_at.date().isoformat(),
            "closes_time": _hora(cohort.closes_at, _CLOSES_DEFAULT_TIME),
            "opens_label": _fecha_hora(cohort.opens_at),
            "closes_label": _fecha_hora(cohort.closes_at),
        },
        "can_edit_window": can_edit,
    }


def _donation_ctx(cohort, *, can_edit: bool) -> dict:
    """Contexto del parcial `cohort/cohort_donation.html` (D5, spec 2026-10-
    01-titulatec-biblioteca-caja-design.md §4.9).

    `amount_raw` precarga el campo del editor en formato de captura
    («800.00»), vacío si la convocatoria no tiene donación capturada (legado
    antes de esta tarea: el alta ya la exige, D19). `amount_label` es la
    lectura de solo lectura (`format_amount`, «Sin capturar» si es `None`).
    """
    from itcj2.apps.titulatec.services.library_clearance_service import format_amount

    amount = cohort.book_donation_amount
    return {
        "cohort_id": cohort.id,
        "donation": {
            "amount_raw": (f"{amount:.2f}" if amount is not None else ""),
            "amount_label": (format_amount(amount) if amount is not None
                             else "Sin capturar"),
        },
        "can_edit_donation": can_edit,
    }


def _cohort_summary_ctx(db, cohort) -> dict:
    from itcj2.apps.titulatec.models import TitulationProcess, ReviewAppointment, PhaseDefinition
    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
    todos = db.query(TitulationProcess).filter_by(cohort_id=cohort.id).all()
    # Una inscripción revocada no es un alumno de la convocatoria: fuera del
    # total, del embudo y de «con cita». Se cuenta aparte (`cancelled`); la
    # pestaña Alumnos sí la lista, etiquetada.
    procs = [p for p in todos if p.status != "cancelled"]
    cancelled = len(todos) - len(procs)
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
        # ISO completo, con hora (spec 2026-09-27 §B3).
        "opens_at": cohort.opens_at.isoformat(),
        "closes_at": cohort.closes_at.isoformat(),
        "total": total, "phase_rows": phase_rows, "with_appt": with_appt,
        "completed": completed, "cancelled": cancelled,
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
def cohort_students(
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
def student_lookup(cohort_id: int, request: Request, control: str = "",
                   user: dict = Depends(require_page_app("titulatec", perms=_COHORT_PERMS))):
    from itcj2.database import SessionLocal
    from itcj2.core.models.user import User
    # MAYÚSCULA antes de buscar: el lookup es un filter_by exacto y una letra
    # en minúscula no encontraría a un alumno ya dado de alta con "B...".
    control = control.strip().upper()
    db = SessionLocal()
    try:
        found = db.query(User).filter_by(control_number=control).first() if control else None
        ctx = {"cohort_id": cohort_id, "control": control,
               "found": ({"name": found.full_name} if found else None),
               "searched": bool(control),
               "programs": _programs(db), "modalities": _modalities(db)}
    finally:
        db.close()
    return render_titulatec(request, "titulatec/partials/cohort_student_addform.html", ctx)


@router.get("/cohorts/{cohort_id}/students/cancel", name="titulatec.pages.admin.student_add_cancel")
def student_add_cancel(cohort_id: int, request: Request,
                      user: dict = Depends(require_page_app("titulatec", perms=_COHORT_PERMS))):
    """Restaura el botón colapsado del alta manual (#student-add)."""
    return render_titulatec(request, "titulatec/partials/cohort_student_addbtn.html", {"cohort_id": cohort_id})


@router.post("/cohorts/{cohort_id}/students", name="titulatec.pages.admin.student_add")
async def student_add(cohort_id: int, request: Request,
                      user: dict = Depends(require_page_app("titulatec", perms=["titulatec.cohort.api.import_csv"]))):
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_student_add, cohort_id=cohort_id, request=request, user=user, form=form)


def _cuerpo_student_add(cohort_id, request, user, form):
    """Cuerpo síncrono de `student_add`: corre en el threadpool, no en el event loop."""
    from fastapi.responses import Response
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import Cohort
    from itcj2.core.models.user import User
    # MAYÚSCULA antes de buscar/crear: `_add_student` -> `ImportService.
    # import_rows` hace el merge con un filter_by exacto, y una letra en
    # minúscula duplicaría la cuenta en vez de encontrar/adjuntar la existente.
    control = (form.get("control_number") or "").strip().upper()
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
def review_days(cohort_id: int, request: Request, month: str = "",
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
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_review_days_toggle, cohort_id=cohort_id, request=request, user=user, form=form)


def _cuerpo_review_days_toggle(cohort_id, request, user, form):
    """Cuerpo síncrono de `review_days_toggle`: corre en el threadpool, no en el event loop."""
    from datetime import datetime
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
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
    # Rol nuevo del Departamento de Titulacion (2026-09-21, Tarea 5): la
    # bandeja `/titulatec/admin/` la resuelve `role_label` con `next(...)`
    # sobre este dict, y sin esta fila el actor cae al "Administración" por
    # omisión aunque su rol real ya exista.
    "titulatec_titulacion": "Titulación",
    "titulatec_school_services": "Servicios Escolares",
    "admin": "Administración",
}


@router.get("/", name="titulatec.pages.admin.home")
def home(
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
def cohorts(
    request: Request,
    error: str = "",
    user: dict = Depends(require_page_app("titulatec", perms=_COHORT_PERMS)),
):
    """Lista de convocatorias + alta (período académico, ventana y donación).

    `?error=ventana` / `?error=donacion` los pone `cohort_create` cuando la
    ventana o la donación del alta no sirven: la página pinta el aviso que
    corresponda y deja el formulario desplegado. Cualquier otro valor se
    ignora.
    """
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
        "window_error": error == "ventana",
        "donation_error": error == "donacion",
    })


@router.post("/cohorts", name="titulatec.pages.admin.cohort_create")
def cohort_create(
    request: Request,
    period_id: int = Form(...),
    opens_date: str = Form(""),
    opens_time: str = Form(""),
    closes_date: str = Form(""),
    closes_time: str = Form(""),
    book_donation: str = Form(""),
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.cohort.api.create"])),
):
    """Alta de convocatoria: nace en `draft`, con su ventana, su donación y su
    lista de requisitos.

    * **`status='draft'`, no `'open'`.** Toda convocatoria nacía abierta con
      `opens_at`/`closes_at` en NULL, así que el predicado de "convocatoria
      pública abierta" era verdadero para TODAS y el formulario público no
      habría sabido a cuál inscribir. La abre el editor de ventana.
    * **La ventana la teclea la jefa** (spec 2026-09-27 §B2): misma regla que
      el panel —fecha obligatoria, hora opcional (vacía = 00:00 / 23:59:59),
      cierre POSTERIOR a la apertura—. Las columnas son NOT NULL, y una
      ventana inventada por el servidor sería una fecha que nadie decidió.
      Si no sirve: 303 a `?error=ventana` ANTES de abrir sesión, sin crear
      nada; la lista pinta el aviso.
    * **La donación voluntaria de libro es OBLIGATORIA al alta** (D19, spec
      2026-10-01-titulatec-biblioteca-caja-design.md §4.9): sin ella,
      Biblioteca no podría pasar ni un caso a Caja
      (`LibraryClearanceService._prepare_registration`). `parse_amount` valida
      el formato y el tope (0 a $100,000, mismas reglas que Biblioteca/Caja);
      inválida o vacía: 303 a `?error=donacion`, ANTES de abrir sesión, igual
      que la ventana —se revisa DESPUÉS de la ventana, así que un alta con las
      dos cosas mal vuelve con el aviso de ventana primero.
    * **Siembra los requisitos de cotejo en la MISMA transacción.** `list_or_seed`
      es perezoso y solo se dispararía desde una página gateada por la fase 2:
      un alumno en fase 1 que contesta la encuesta no tendría requisito que
      acreditar y el crédito se perdería en silencio.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import Cohort
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )
    from itcj2.apps.titulatec.services.library_clearance_service import parse_amount
    from itcj2.core.models.academic_period import AcademicPeriod

    apertura = _parse_window_dt(opens_date, opens_time, default=_OPENS_DEFAULT_TIME)
    cierre = _parse_window_dt(closes_date, closes_time, default=_CLOSES_DEFAULT_TIME)
    if apertura is None or cierre is None or cierre <= apertura:
        return RedirectResponse("/titulatec/admin/cohorts?error=ventana", status_code=303)
    try:
        donacion = parse_amount(book_donation)
    except ValueError:
        return RedirectResponse("/titulatec/admin/cohorts?error=donacion", status_code=303)

    db = SessionLocal()
    try:
        if not db.query(Cohort).filter_by(period_id=period_id).first():
            period = db.get(AcademicPeriod, period_id)
            cohort = Cohort(
                period_id=period_id,
                name=f"Convocatoria Titulación {period.code if period else period_id}",
                status="draft", created_by_id=int(user["sub"]),
                opens_at=apertura, closes_at=cierre,
                book_donation_amount=donacion,
            )
            db.add(cohort)
            db.flush()          # hace falta el id para sembrar
            CotejoRequirementService.seed_defaults(db, cohort.id, commit=False)
            db.commit()
    finally:
        db.close()
    return RedirectResponse("/titulatec/admin/cohorts", status_code=303)


@router.get("/cohorts/{cohort_id}", name="titulatec.pages.admin.cohort_detail")
def cohort_detail(cohort_id: int, request: Request, tab: str = "resumen",
                  user: dict = Depends(require_page_app("titulatec", perms=_COHORT_PERMS))):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import Cohort
    from itcj2.core.services.authz_cache import cached_perms
    tab = tab if tab in ("resumen", "dias", "alumnos", "importar", "cotejo") else "resumen"
    db = SessionLocal()
    try:
        cohort = db.get(Cohort, cohort_id)
        if not cohort:
            return Response(status_code=404)
        perms = cached_perms(db, int(user["sub"]), "titulatec")
        ctx = {"cohort": cohort.to_dict(), "cohort_id": cohort_id, "tab": tab,
               "can_edit_days": "titulatec.cohort.api.review_days" in perms,
               "window_header": {"opens": _fecha_hora(cohort.opens_at),
                                 "closes": _fecha_hora(cohort.closes_at)}}
        if tab == "resumen":
            ctx["summary"] = _cohort_summary_ctx(db, cohort)
            ctx.update(_window_ctx(
                db, cohort, can_edit="titulatec.cohort.api.update" in perms))
            ctx.update(_donation_ctx(
                cohort, can_edit="titulatec.cohort.api.update" in perms))
        elif tab == "importar":
            pass  # el wizard de importación se sirve con el cohort ya en ctx
        elif tab == "dias":
            from datetime import date as _d
            today = _d.today()
            ctx["days"] = _review_days_ctx(db, cohort_id, today.year, today.month)
        elif tab == "alumnos":
            ctx.update(_students_ctx(db, cohort_id, q="", phase=None, page=1))
        elif tab == "cotejo":
            # `_cotejo_reqs_ctx` vuelve a pedir los permisos (ya están en `perms`
            # de arriba), pero `cached_perms` es una lectura de Redis y la ruta
            # suelta necesita el helper autocontenido: se deja la llamada tal
            # cual para que el editor tenga UNA sola forma de armarse.
            ctx.update(_cotejo_reqs_ctx(db, cohort_id, int(user["sub"])))
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/cohort_detail.html", ctx)


# ===========================================================================
# Requisitos de cotejo por convocatoria
# ===========================================================================
# Las URL las dicta el parcial `partials/cohort/cohort_cotejo_reqs.html`, que
# existe desde el rediseño de Citas y posteaba a tres rutas inexistentes
# (`:15`, `:36`, `:50`). Su raíz es `id="cotejo-reqs-body"` y TODOS sus controles
# usan `hx-target="#cotejo-reqs-body" hx-swap="outerHTML"`, así que las cuatro
# rutas devuelven el parcial COMPLETO, nunca una fila.
#
# UN SOLO permiso en la lista, y a propósito: `require_page_app` la evalúa como
# OR (`itcj2/dependencies.py:131`). Cualquier `dashboard.*` que se cuele aquí
# abre el editor de la convocatoria al encargado de carrera, igual que pasó con
# `_COHORT_PERMS`. La pestaña de `cohort_detail` tampoco es motivo para ensanchar
# esta lista: esa página va por `_COHORT_PERMS` y el parcial se pinta en solo
# lectura cuando `can_edit_reqs` es False.
_COTEJO_REQ_PERMS = ["titulatec.cohort.api.cotejo_reqs"]

_TT_COTEJO_PARTIAL = "titulatec/partials/cohort/cohort_cotejo_reqs.html"


def _cotejo_reqs_ctx(db, cohort_id: int, user_id: int) -> dict:
    """Contexto del parcial. `active_only=False`: el editor sí lista los inactivos.

    Desactivar es la vía soportada en vez de borrar (un requisito con
    cumplimientos NO se puede borrar), así que ocultarlos aquí dejaría al usuario
    sin forma de reactivarlos. El parcial ya los pinta con `opacity-50`.

    `CotejoRequirementService.list`, NO `list_or_seed`: un GET jamás siembra. La
    convocatoria nace con sus requisitos (Tarea 4, `cohort_create`), y si alguna
    vieja no los tiene, el editor muestra el vacío y la jefa los agrega.

    `info_by_req` es la «Información para el alumno» de cada requisito YA
    re-sanitizada: la segunda sanitización del diseño, al PINTAR (la primera es
    al guardar, en el servicio), para que una fila escrita por fuera del editor
    —un UPDATE a mano, un DML— tampoco inyecte. Sin tope (`max_len=None`): una
    fila vieja nunca tumba la página. El parcial pinta con `|safe` SOLO este
    mapa, nunca `r.info_html`.
    """
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )
    from itcj2.apps.titulatec.utils.rich_text import sanitize_info_html
    from itcj2.core.services.authz_cache import cached_perms

    perms = cached_perms(db, user_id, "titulatec")
    reqs = CotejoRequirementService.list(db, cohort_id, active_only=False)
    return {
        "reqs": reqs,
        "cohort_id": cohort_id,
        "can_edit_reqs": "titulatec.cohort.api.cotejo_reqs" in perms,
        "info_by_req": {r.id: sanitize_info_html(r.info_html, max_len=None) for r in reqs},
    }


@router.get("/cohorts/{cohort_id}/cotejo-reqs", name="titulatec.pages.admin.cotejo_reqs")
def cotejo_reqs(
    cohort_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=_COTEJO_REQ_PERMS)),
):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _cotejo_reqs_ctx(db, cohort_id, int(user["sub"]))
        return render_titulatec(request, _TT_COTEJO_PARTIAL, ctx)
    finally:
        db.close()


@router.post("/cohorts/{cohort_id}/cotejo-reqs", name="titulatec.pages.admin.cotejo_req_create")
async def cotejo_req_create(
    cohort_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=_COTEJO_REQ_PERMS)),
):
    """Agrega un requisito, con su «Información para el alumno» si la trae.

    `info_html` llega CRUDO del editor (input oculto del formulario de alta) y lo
    sanitiza el servicio. Excederse del tope es 400 + `X-Tt-Error` sin escribir
    nada: htmx no swappea en 4xx, así que el editor conserva lo escrito.
    """
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_cotejo_req_create, cohort_id=cohort_id, request=request, user=user, form=form)


def _cuerpo_cotejo_req_create(cohort_id, request, user, form):
    """Cuerpo síncrono de `cotejo_req_create`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )
    from itcj2.apps.titulatec.utils.rich_text import InfoHtmlTooLong

    label = (form.get("label") or "").strip()
    if not label:
        return Response(status_code=400,
                        headers={"X-Tt-Error": _hdr("Escribe el nombre del requisito.")})
    info = form.get("info_html")
    db = SessionLocal()
    try:
        try:
            CotejoRequirementService.create(
                db, cohort_id, label=label,
                hint=((form.get("hint") or "").strip() or None),
                icon=((form.get("icon") or "").strip() or None),
                is_required=bool(form.get("is_required")),
                # Un campo que no es texto (un archivo con ese nombre) se ignora.
                info_html=(info if isinstance(info, str) else None),
            )
        except InfoHtmlTooLong as exc:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        ctx = _cotejo_reqs_ctx(db, cohort_id, int(user["sub"]))
        return render_titulatec(request, _TT_COTEJO_PARTIAL, ctx)
    finally:
        db.close()


@router.post("/cohorts/{cohort_id}/cotejo-reqs/{rid}/update",
             name="titulatec.pages.admin.cotejo_req_update")
async def cotejo_req_update(
    cohort_id: int,
    rid: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=_COTEJO_REQ_PERMS)),
):
    """Actualiza etiqueta, detalle, ícono, las dos casillas y la información.

    `code`/`auto_source` NO son editables: los siembra `seed_defaults` y son la
    identidad estable del requisito. Y **no hay input de `order_index`** en el
    parcial, así que aquí no se toca: pasarlo como `None` lo dejaría igual, pero
    ni siquiera se menciona para que nadie lo añada sin cambiar el formulario.

    `info_html` se pasa SOLO si el formulario lo trae: para el servicio su
    presencia es la intención (ausente = no se toca; vacío = se borra). Un
    formulario sin editor —una pestaña abierta antes de este cambio— no borra la
    información. Excederse del tope es 400 + `X-Tt-Error` sin escribir nada.
    """
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_cotejo_req_update, cohort_id=cohort_id, rid=rid, request=request, user=user,
        form=form)


def _cuerpo_cotejo_req_update(cohort_id, rid, request, user, form):
    """Cuerpo síncrono de `cotejo_req_update`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )
    from itcj2.apps.titulatec.utils.rich_text import InfoHtmlTooLong

    label = (form.get("label") or "").strip()
    if not label:
        return Response(status_code=400,
                        headers={"X-Tt-Error": _hdr("Escribe el nombre del requisito.")})
    # Las casillas ausentes son False, no "sin cambio": un checkbox que el
    # navegador no envía es exactamente el usuario desmarcándolo.
    campos = {
        "label": label,
        "hint": ((form.get("hint") or "").strip() or None),
        "icon": ((form.get("icon") or "").strip() or None),
        "is_required": bool(form.get("is_required")),
        "is_active": bool(form.get("is_active")),
    }
    info = form.get("info_html")
    if isinstance(info, str):
        campos["info_html"] = info
    db = SessionLocal()
    try:
        try:
            CotejoRequirementService.update(db, rid, cohort_id, **campos)
        except InfoHtmlTooLong as exc:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        ctx = _cotejo_reqs_ctx(db, cohort_id, int(user["sub"]))
        return render_titulatec(request, _TT_COTEJO_PARTIAL, ctx)
    finally:
        db.close()


@router.post("/cohorts/{cohort_id}/cotejo-reqs/{rid}/delete",
             name="titulatec.pages.admin.cotejo_req_delete")
def cotejo_req_delete(
    cohort_id: int,
    rid: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=_COTEJO_REQ_PERMS)),
):
    """Borra el requisito, con dos negativas.

    * Un requisito con `auto_source` no se borra desde la UI: `create()` no puede
      fijar ese campo, así que borrarlo dejaría a la encuesta sin nada que
      acreditar en esa convocatoria y sin forma de restaurarlo.
    * Un requisito que alguien ya cumplió tampoco: la FK de los cumplimientos es
      `ON DELETE RESTRICT`, y borrarlo destruiría el crédito dejando la bitácora
      contradiciendo el estado.

    `not_found` NO es error: el `delete` de la Tarea 4 devuelve `(False,
    "not_found")` y aquí se re-renderiza la lista, que es lo correcto para htmx
    (la fila ya no está; el swap deja al usuario viendo el estado real).
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import CotejoRequirement
    from itcj2.apps.titulatec.services.cotejo_requirement_service import (
        CotejoRequirementService,
    )

    db = SessionLocal()
    try:
        item = db.query(CotejoRequirement).filter_by(id=rid, cohort_id=cohort_id).first()
        if item is not None and item.auto_source:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(
                "Ese requisito lo acredita el sistema: desactívalo en vez de borrarlo.")})
        ok, motivo = CotejoRequirementService.delete(db, rid, cohort_id)
        if not ok and motivo.startswith("fulfilled:"):
            n = motivo.split(":", 1)[1]
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(
                f"Ese requisito ya lo cumplieron {n} alumnos; "
                f"desactívalo en vez de borrarlo.")})
        ctx = _cotejo_reqs_ctx(db, cohort_id, int(user["sub"]))
        return render_titulatec(request, _TT_COTEJO_PARTIAL, ctx)
    finally:
        db.close()


@router.post("/cohorts/{cohort_id}/ventana", name="titulatec.pages.admin.cohort_window")
def cohort_window(
    cohort_id: int,
    request: Request,
    status: str = Form(...),
    opens_date: str = Form(""),
    opens_time: str = Form(""),
    closes_date: str = Form(""),
    closes_time: str = Form(""),
    opens_at: str = Form(""),
    closes_at: str = Form(""),
    user: dict = Depends(require_page_app("titulatec",
                                          perms=["titulatec.cohort.api.update"])),
):
    """Escribe la ventana de inscripción pública y aplica la pausa/reanudación.

    Cada extremo llega como fecha (`*_date`, `YYYY-MM-DD`, obligatoria) + hora
    (`*_time`, `HH:MM`, opcional) y se lee con `_parse_window_dt`: hora vacía =
    00:00 en la apertura y 23:59:59 en el cierre (spec 2026-09-27 D8). Fecha
    vacía o ilegible, u hora ilegible → 400 con «La apertura y el cierre son
    obligatorios.», sin tocar la convocatoria (columnas NOT NULL).

    `opens_at`/`closes_at` son los nombres del formulario de ANTES de la hora
    (solo fecha): se aceptan como la fecha del extremo cuando no llega
    `*_date`, para que una pestaña con el formulario viejo en caché guarde con
    la hora de omisión en vez de estrellarse en «obligatorios». Solo respaldo:
    la plantilla ya no los postea.

    Solo la ventana: el interruptor «Aprobación automática (SII)» se retiró con
    la automática (spec 2026-09-27 §A3). Un formulario viejo en caché que aún
    mande sus campos no mueve nada: la ruta ya no los lee, y la columna queda
    en la BD como legado sin uso (ver el modelo `Cohort`).

    UN SOLO código en `perms`, y el específico. `require_page_app` evalúa la
    lista como OR (`dependencies.py:131`): un `dashboard.*` de más abriría el
    interruptor que pausa los procesos de toda una convocatoria a cualquier
    oficial (es el incidente documentado en `_COHORT_PERMS`, arriba).

    `titulatec.cohort.api.update` lleva sembrado desde el primer DML
    (`02_insert_permissions.sql:44`) y hasta ahora no gateaba nada.

    El flip de procesos NO se replica aquí: `CohortService.set_window` es el
    actor único de D5 y hace el ÚNICO `commit`. Esta ruta no confirma nada:
    llama y pinta.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.cohort_service import CohortService
    from itcj2.core.services.authz_cache import cached_perms
    from itcj2.apps.titulatec.models import Cohort

    db = SessionLocal()
    try:
        cohort = db.get(Cohort, cohort_id)
        if cohort is None:
            return Response(status_code=404)
        apertura = _parse_window_dt(opens_date or opens_at, opens_time,
                                    default=_OPENS_DEFAULT_TIME)
        cierre = _parse_window_dt(closes_date or closes_at, closes_time,
                                  default=_CLOSES_DEFAULT_TIME)
        if apertura is None or cierre is None:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(
                "La apertura y el cierre son obligatorios.")})
        try:
            res = CohortService.set_window(
                db, cohort_id, opens_at=apertura, closes_at=cierre,
                status=(status or "").strip(), actor_id=int(user["sub"]),
            )
        except ValueError as exc:
            # htmx NO swappea en 4xx: el mensaje viaja en el header y lo pinta el
            # escucha de `base_admin.html:100-108`. `_hdr` lo percent-codifica
            # porque los headers son latin-1 y todos nuestros textos van con
            # acentos.
            #
            # SIN `db.rollback()`, a propósito. `CohortService.set_window` lanza
            # sus ValueError —estado desconocido, convocatoria inexistente,
            # extremo faltante y `closes_at <= opens_at`— ANTES de su primera
            # escritura, así que no hay nada que deshacer. Y un rollback "por
            # si acaso" no es gratis: bajo el
            # `join_transaction_mode="create_savepoint"` del harness
            # emite ROLLBACK TO SAVEPOINT y descarta también las filas que
            # sembraron las fábricas —la jefa, su rol, sus permisos y la
            # convocatoria—, con lo que el `db_session.refresh(cohort)` de
            # `test_el_cierre_anterior_a_la_apertura_se_rechaza` reventaría con
            # `ObjectDeletedError`. El repo ya escarmentó en
            # `pages/appointments.py`: si algún día hiciera falta un rollback
            # aquí, va gateado por la clase de error que de verdad envenena la
            # transacción de Postgres, nunca en el `except` entero.
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})

        perms = cached_perms(db, int(user["sub"]), "titulatec")
        ctx = _window_ctx(db, cohort,
                          can_edit="titulatec.cohort.api.update" in perms)
    finally:
        db.close()

    partes = []
    if res["paused"]:
        partes.append(f"{res['paused']} proceso(s) en pausa")
    if res["resumed"]:
        partes.append(f"{res['resumed']} proceso(s) reanudado(s)")
    aviso = "Ventana guardada" + (f": {', '.join(partes)}." if partes else ".")

    resp = render_titulatec(request, "titulatec/partials/cohort/cohort_window.html", ctx)
    resp.headers["X-Tt-Notice"] = _hdr(aviso)
    resp.headers["X-Tt-Notice-Kind"] = "success"
    return resp


@router.post("/cohorts/{cohort_id}/donacion", name="titulatec.pages.admin.cohort_donation")
def cohort_donation(
    cohort_id: int,
    request: Request,
    book_donation: str = Form(""),
    user: dict = Depends(require_page_app("titulatec",
                                          perms=["titulatec.cohort.api.update"])),
):
    """Edita la donación voluntaria de libro de la convocatoria (D5, spec
    2026-10-01-titulatec-biblioteca-caja-design.md §4.9), desde el panel
    Resumen.

    UN SOLO código en `perms`, y el específico: mismo motivo que
    `cohort_window` (`require_page_app` evalúa la lista como OR,
    `dependencies.py:131`).

    `parse_amount` valida formato y tope (0 a $100,000); inválido → 400 +
    `X-Tt-Error`, sin tocar la convocatoria. `CohortService.set_book_donation`
    es la dueña de la transacción (UN commit) y devuelve cuántos
    `LibraryClearance` de esta convocatoria YA tienen un monto congelado
    (Review Focus #2): ese número arma el aviso «N egresados ya tienen monto
    asignado; no cambia para ellos (Biblioteca puede corregir)» cuando es > 0,
    o «Donación guardada.» a secas si nadie se ve afectado.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import Cohort
    from itcj2.apps.titulatec.services.cohort_service import CohortService
    from itcj2.apps.titulatec.services.library_clearance_service import parse_amount
    from itcj2.core.services.authz_cache import cached_perms

    db = SessionLocal()
    try:
        cohort = db.get(Cohort, cohort_id)
        if cohort is None:
            return Response(status_code=404)
        try:
            monto = parse_amount(book_donation)
            result = CohortService.set_book_donation(db, cohort_id, amount=monto)
        except ValueError as exc:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})

        perms = cached_perms(db, int(user["sub"]), "titulatec")
        ctx = _donation_ctx(cohort, can_edit="titulatec.cohort.api.update" in perms)
    finally:
        db.close()

    n = result["affected"]
    if n:
        aviso = (f"Donación guardada. {n} egresado{'s' if n != 1 else ''} ya "
                f"tiene{'n' if n != 1 else ''} monto asignado; no cambia para "
                "ellos (Biblioteca puede corregir).")
    else:
        aviso = "Donación guardada."

    resp = render_titulatec(request, "titulatec/partials/cohort/cohort_donation.html", ctx)
    resp.headers["X-Tt-Notice"] = _hdr(aviso)
    resp.headers["X-Tt-Notice-Kind"] = "warning" if n else "success"
    return resp


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
def import_page(
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
    raw = await archivo.read()
    return await run_in_threadpool(
        _cuerpo_import_upload, cohort_id=cohort_id, request=request, raw=raw)


def _cuerpo_import_upload(cohort_id, request, raw):
    """Cuerpo síncrono de `import_upload`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.import_service import ImportService

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
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_import_revalidate, cohort_id=cohort_id, request=request, form=form)


def _cuerpo_import_revalidate(cohort_id, request, form):
    """Cuerpo síncrono de `import_revalidate`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.import_service import ImportService

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
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_import_commit, cohort_id=cohort_id, request=request, user=user, form=form)


def _cuerpo_import_commit(cohort_id, request, user, form):
    """Cuerpo síncrono de `import_commit`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import Cohort
    from itcj2.apps.titulatec.services.import_service import ImportService

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

# Cómo se lee cada suceso del expediente. La voz es la del PERSONAL, no la del
# alumno: en `pages/student.py` el mismo evento dice «Confirmaste tu asistencia»
# y aquí «El alumno confirmó». Un evento sin entrada aquí se pinta con su código
# crudo en vez de desaparecer: un historial que se calla no es un historial.
_EVENT_UI = {
    "process_created":              ("Alta en la convocatoria",   "person-plus",            "neutral"),
    # Alta por el formulario publico, no por CSV ni a mano: al oficial le dice
    # por que este expediente existe sin que el lo capturara.
    "enrollment_self_service":      ("Se inscribió por el formulario", "globe",              "neutral"),
    # `EnrollmentRequestService.reassign_nip`: el correo con el NIP no salió y
    # Centro de Computo le dio uno nuevo. El payload nunca lleva el NIP.
    "enrollment_access_reset":      ("Se reasignó el NIP de acceso", "key",                  "neutral"),
    # Los escribe `CohortService.set_window` al cerrar y reabrir la convocatoria.
    # Explican por que un proceso se quedo quieto sin accion de nadie.
    "process_paused":               ("Proceso pausado",           "pause-circle",           "amber"),
    "process_resumed":              ("Proceso reanudado",         "arrow-clockwise",        "neutral"),
    # `ProcessService.cancel`. El motivo viaja en el payload (`reason`) y
    # `_evento_detalle` ya lo pinta.
    "process_cancelled":            ("Inscripción revocada",      "slash-circle",           "danger"),
    "document_uploaded":            ("Subió un documento",        "cloud-arrow-up",         "neutral"),
    "document_approved":            ("Documento aprobado",        "check-lg",               "success"),
    "document_rejected":            ("Documento rechazado",       "x-lg",                   "danger"),
    "document_deleted":             ("Documento eliminado",       "trash",                  "danger"),
    "phase_approved":               ("Fase aprobada",             "check-circle",           "success"),
    "phase_rejected":               ("Fase rechazada",            "exclamation-triangle",   "danger"),
    "requirement_fulfilled":        ("Requisito acreditado",      "check2-square",          "success"),
    "requirement_unfulfilled":      ("Requisito desmarcado",      "square",                 "amber"),
    "process_completed":            ("Proceso completado",        "trophy",                 "success"),
    "appointment_scheduled":        ("Cita agendada",             "calendar-plus",          "neutral"),
    "appointment_confirmed":        ("El alumno confirmó",        "check2-circle",          "success"),
    "appointment_rescheduled":      ("Cita reagendada",           "arrow-repeat",           "amber"),
    "appointment_change_requested": ("El alumno pidió otro día",  "chat-left-dots",         "amber"),
    "appointment_in_progress":      ("Cotejo iniciado",           "play-circle",            "neutral"),
    "appointment_attended":         ("Cotejo atendido",           "check-circle",           "success"),
    "appointment_no_show":          ("No se presentó",            "person-x",               "danger"),
    "appointment_undo_no_show":     ("Se deshizo la falta",       "arrow-counterclockwise", "amber"),
    # Lo escribe `AppointmentService.cancel`, que comparten el alumno y el
    # encargado: la etiqueta es NEUTRAL porque el mismo `event_type` sirve a los
    # dos y «El alumno cancelo» seria mentira cuando cancelo la ventanilla.
    "appointment_cancelled":        ("Cita cancelada",            "calendar-x",             "danger"),
    # Liberacion de la encuesta de egresados (GTV). Faltaban los cuatro, asi que
    # el expediente enseñaba `survey_review_approved` en crudo.
    "survey_review_submitted":      ("Envió la encuesta de egresados", "clipboard-check",   "neutral"),
    "survey_review_approved":       ("GTV liberó la encuesta",    "patch-check",            "success"),
    "survey_review_rejected":       ("GTV dejó observaciones",    "chat-left-text",         "amber"),
    "survey_review_revoked":        ("Se revocó la liberación",   "arrow-counterclockwise", "amber"),
    # Constancia previa de la encuesta (D9, spec 2026-10-01-titulatec-
    # biblioteca-caja-design.md §4.12): `SurveyReviewService.register_prior`.
    "survey_review_prior":          ("Se liberó por constancia previa", "file-earmark-check", "success"),
    "survey_paper_delivered":       ("Se entregó la constancia de liberación en papel", "file-earmark-check", "success"),
    # ---- No adeudo de biblioteca (Biblioteca -> Caja), spec 2026-10-01 ----
    "library_debt_registered":      ("Biblioteca registró el adeudo", "cash-coin",          "amber"),
    "library_no_charge":            ("Biblioteca registró sin adeudo", "check2-square",     "success"),
    "library_amount_corrected":     ("Biblioteca corrigió el monto", "pencil-square",       "amber"),
    "library_payment_registered":   ("Caja registró el pago",     "cash-stack",             "success"),
    "library_prior_registered":     ("Se registró una constancia previa", "file-earmark-check", "success"),
    "library_payment_reverted":     ("Caja revirtió el pago",     "arrow-counterclockwise", "amber"),
    "library_clearance_reverted":   ("Biblioteca revirtió la liberación", "arrow-counterclockwise", "amber"),
    "library_prior_undone":         ("Se deshizo la constancia previa", "arrow-counterclockwise", "amber"),
    # «Con observaciones» (spec 2026-10-05 §3.4), gemelos de `survey_review_
    # rejected`/`_revoked`. El motivo viaja en `reason` y `_evento_detalle` lo
    # pinta; el de rehabilitar guarda el anterior como `previous_reason`, que
    # a propósito no se repite (ya está en su `library_observed`).
    "library_observed":             ("Biblioteca registró observaciones", "chat-left-text", "amber"),
    "library_reenabled":            ("Biblioteca activó su trámite", "arrow-clockwise",     "neutral"),
}

# Estado de `EmailOutbox.status` -> (etiqueta, tono) para la píldora de la
# zona «Correos» del expediente (spec 2026-09-28-titulatec-correos-
# notificaciones §7). Dominio cerrado en `OUTBOX_STATUSES`
# (`models/email_outbox.py`): un estado nuevo ahí también necesita entrada
# aquí, o se pinta con su código crudo (mismo respaldo que `_EVENT_UI`).
_MAIL_STATUS_UI = {
    "sent":         ("Enviado",              "success"),
    "pending":      ("En cola",              "neutral"),
    "failed":       ("Falló",                "danger"),
    "no_recipient": ("Sin correo personal",  "amber"),
    "obsolete":     ("Ya no aplicaba",       "neutral"),
}
# `no_recipient` dice a QUÉ buzón le faltó, y eso depende del tipo: los correos
# del proceso van SOLO al personal («Sin correo personal», arriba), pero los de
# inscripción (`ENROLLMENT_KINDS`) van al institucional (folio, «ya inscrito»)
# o a los dos (revocación) -`mail_dispatch._destinatarios_inscripcion`-, así
# que ahí la píldora no nombra un buzón que quizá ni era el destino.
_SIN_DESTINATARIO_INSCRIPCION = "Sin correo"

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
    ("/titulatec/admin/correos", "Correos"),
    ("/titulatec/admin/liberados", "Liberados"),
)
_BACK_DEFAULT = "/titulatec/admin/processes"
_BACK_LIBERADOS = "/titulatec/admin/liberados"
# Ni lista ni Liberados (nadie así con el DML del 2026-10-07; el expediente se
# abre con `process.page.detail` solo): el landing lo manda a SU pantalla.
_BACK_INICIO = "/titulatec/"


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


def _bitacora_correos(filas) -> list[dict]:
    """Entradas de la zona «Correos» del expediente: UNA por CORREO, no por
    aviso (ruling 21, spec §7). `filas` = `StudentMail.history` (más nuevas
    primero).

    Las filas de un mismo grupo (`group_key` no nulo) con el mismo `status` y
    el mismo `sent_at` son un solo correo —el despachador marca toda la unidad
    igual— y se juntan en la entrada de la fila MÁS RECIENTE (su id es el de la
    entrada: estable para el morph), con `n` = cuántos avisos junta. Las filas
    sueltas son una entrada cada una. La fecha es la de ENVÍO si salió; si no,
    la de alta del aviso más reciente.

    Dicts PLANOS: `process_detail` renderiza DESPUÉS del `db.close()` de la ruta.
    `kind` es `String(40)` SIN CHECK en BD (fix round 1, ronda de arreglo 1):
    `StudentMail.enqueue` valida contra `OUTBOX_KINDS` antes de escribir, pero
    no es el único camino posible hacia la tabla (migración de datos a mano,
    `kind` nuevo del catálogo sin actualizar `KIND_LABELS`...), así que se
    degrada con `.get(kind, kind)` —mismo patrón que `_MAIL_STATUS_UI.get(...)`
    y `_EVENT_UI.get(...)`—: un `kind` sin etiqueta NUNCA debe tumbar TODO el
    expediente con un `KeyError` por una sola fila; test:
    `test_expediente_mail.py::test_kind_desconocido_no_revienta_la_pagina`.
    """
    from itcj2.apps.titulatec.models.email_outbox import ENROLLMENT_KINDS
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    entradas: list[dict] = []
    por_correo: dict[tuple, dict] = {}
    for m in filas:
        llave = (m.group_key, m.status, m.sent_at) if m.group_key else None
        if llave in por_correo:
            por_correo[llave]["n"] += 1
            continue
        etiqueta, tono = _MAIL_STATUS_UI.get(m.status, (m.status, "neutral"))
        if m.status == "no_recipient" and m.kind in ENROLLMENT_KINDS:
            etiqueta = _SIN_DESTINATARIO_INSCRIPCION
        enviado = m.status == "sent" and m.sent_at is not None
        entrada = {
            "id": m.id,
            "when": _fecha_larga(m.sent_at if enviado else m.created_at),
            # El asunto solo existe una vez enviado: antes, el nombre del tipo.
            "subject": m.subject or StudentMail.KIND_LABELS.get(m.kind, m.kind),
            "to": m.sent_to or "—",
            "status": m.status,
            "status_label": etiqueta,
            "tone": tono,
            "error": m.last_error,
            "n": 1,
        }
        if llave is not None:
            por_correo[llave] = entrada
        entradas.append(entrada)
    return entradas


def _back_por_omision(abiertas: dict | None) -> dict:
    """Regresar sin `from` válido (spec 2026-10-07 §1.2): Procesos SOLO si el
    actor puede abrir la lista; si no y puede Liberados, Liberados; si no, el
    inicio de la app. `abiertas=None` (sin actor) conserva Procesos, el
    histórico."""
    if abiertas is None or abiertas.get("processes"):
        return {"url": _BACK_DEFAULT, "label": "Procesos"}
    if abiertas.get("liberados"):
        return {"url": _BACK_LIBERADOS, "label": "Liberados"}
    return {"url": _BACK_INICIO, "label": "Inicio"}


def _back_ctx(raw: str | None, abiertas: dict | None = None) -> dict:
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

    Lo que no pasa cae al regreso por omisión (`_back_por_omision`): Procesos,
    de donde se llegaba históricamente, solo si el actor puede abrir la lista;
    si no, Liberados (Titulación, D1) o el inicio de la app. `abiertas` es
    `_tabs_abiertas(cached_perms(...))`.
    """
    url = (raw or "").strip()
    valido = (
        url.startswith("/titulatec/admin/")
        and not url.startswith("//")
        and ".." not in url
        and "\\" not in url
    )
    if not valido:
        return _back_por_omision(abiertas)
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
    # Los sucesos de requisito traen `label` (la etiqueta congelada al
    # acreditar) y un `source` que aqui significa QUIEN acredito
    # (officer|system|self_service), no el origen del alta. `unfulfill` guarda
    # ese dato como `source_previo`, que es lo unico que sobrevive al borrado.
    if ev.event_type in ("requirement_fulfilled", "requirement_unfulfilled"):
        etiqueta = p.get("label") or p.get("code")
        origen = {"officer": "en ventanilla", "system": "por el sistema",
                  "self_service": "por el alumno"}.get(
                      p.get("source") or p.get("source_previo"))
        return " · ".join([x for x in (etiqueta, origen) if x]) or None
    partes = []
    code = p.get("type_code")
    if code:
        partes.append(doc_names.get(code, code))
    if p.get("version"):
        partes.append(f"v{p['version']}")
    if p.get("scheduled_at"):
        # El payload la guarda en ISO. Enseñarla asi («2026-09-07 09:30») rompe
        # la lectura justo en la linea donde el resto de la pantalla dice
        # «7 sep 2026 · 09:30».
        crudo = str(p["scheduled_at"])
        try:
            from datetime import datetime
            partes.append(_fecha_larga(datetime.fromisoformat(crudo)))
        except ValueError:
            partes.append(crudo.replace("T", " ")[:16])
    if p.get("source"):
        partes.append("importación CSV" if p["source"] == "csv" else "alta manual")
    texto = " · ".join(partes)
    motivo = p.get("note") or p.get("reason")
    if motivo:
        texto = f"{texto} — {motivo}" if texto else str(motivo)
    return texto or None


def _detail_ctx(db, process_id: int, *, user_id: int | None = None, open_phase=None,
                back_raw=None, doc_abierto=None) -> dict | None:
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
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.format_b_service import FormatBService
    from itcj2.apps.titulatec.services.process_service import ProcessService
    from itcj2.apps.titulatec.services.track_service import TrackService
    from itcj2.apps.titulatec.utils import storage

    proc = db.get(TitulationProcess, process_id)
    if not proc:
        return None
    student = db.get(User, proc.student_id)
    cohort = db.get(Cohort, proc.cohort_id)
    modality = db.get(Modality, proc.modality_id) if proc.modality_id else None
    program = db.get(Program, proc.program_id) if proc.program_id else None

    # Perfil del proceso (spec 2026-09-30-titulatec-posgrado-design.md §4.4,
    # Tarea 4): licenciatura/"sin carrera" -> los 3 documentos de siempre;
    # posgrado -> los 7. `program` ya está cargado arriba (para `program_name`),
    # así que `for_level` reusa ese objeto en vez de que `TrackService.
    # for_process` repita el `db.get(Program, ...)`.
    track = TrackService.for_level(program.level if program else None)
    initial_codes = DocumentService.initial_doc_types(track)

    # ---- catálogos y filas del proceso, por lote ----
    pdefs = (db.query(PhaseDefinition).filter_by(is_active=True)
             .order_by(PhaseDefinition.order_index).all())
    fases_db = {ph.phase_number: ph for ph in
                db.query(ProcessPhase).filter_by(process_id=process_id).all()}
    # Sin `is_active`: si un tipo se desactiva, el documento ya subido tiene que
    # seguir mostrándose con su nombre y no con el código crudo.
    tipos = {t.code: t.name for t in db.query(DocumentType)
             .filter(DocumentType.code.in_(initial_codes)).all()}
    doc_names = {code: tipos.get(code, code) for code in initial_codes}
    docs_db = {d.type_code: d for d in db.query(Document)
               .filter(Document.process_id == process_id,
                       Document.type_code.in_(initial_codes)).all()}

    eventos = (db.query(ProcessEvent).filter_by(process_id=process_id)
               .order_by(ProcessEvent.created_at, ProcessEvent.id).all())
    actor_ids = {e.actor_id for e in eventos if e.actor_id}
    actor_ids |= {ph.reviewed_by_id for ph in fases_db.values() if ph.reviewed_by_id}
    actor_ids |= {d.reviewed_by_id for d in docs_db.values() if d.reviewed_by_id}
    actores = ({u.id: u.full_name for u in db.query(User).filter(User.id.in_(actor_ids)).all()}
               if actor_ids else {})

    # ---- documentos de la fase 1 (solo lectura) ----
    # R-G (spec 2026-09-30-titulatec-posgrado-design.md §5, invariante 8;
    # Ruling R11, revisión final): `docs_db` YA es el lote completo (arriba),
    # así que el `present_codes` de `excused_initial_docs` (predicado PURO,
    # sin `db`) sale de ahí sin consulta extra. `initial_docs_phase` solo se
    # pregunta si hace falta -- algún extra de posgrado sin fila -- para que
    # un expediente de licenciatura (que nunca tiene codigos en
    # `POSGRADO_EXTRA_DOCS`) no pague esa consulta.
    present_codes = frozenset(docs_db.keys())
    initial_docs_phase = None
    if any(code in DocumentService.POSGRADO_EXTRA_DOCS and code not in present_codes
           for code in initial_codes):
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        initial_docs_phase = PhaseService.phase_number_for_code(db, "initial_docs")
    excused = DocumentService.excused_initial_docs(
        proc, present_codes, initial_docs_phase=initial_docs_phase)

    docs = []
    for code in initial_codes:
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
            "excused": doc is None and code in excused,
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

    # ---- requisitos de cotejo de la fase 2 (§5.4) ----
    #
    # Lectura NO SEMBRADORA a proposito. `RequirementService.list_with_status`
    # enruta a `CotejoRequirementService.list_or_seed` -> `seed_defaults(
    # commit=True)`: un simple GET del expediente COMMITEARIA ocho filas en la
    # convocatoria del alumno. Aqui se copia la forma de consulta de
    # `RequirementService.missing_required`, que ya es la no sembradora, y se
    # deja la siembra donde pertenece (crear la convocatoria y acreditar la
    # encuesta).
    from itcj2.apps.titulatec.models import CotejoRequirement, RequirementFulfillment
    from itcj2.apps.titulatec.services.requirement_service import DONE_STATUSES

    req_rows = (db.query(CotejoRequirement)
                .filter_by(cohort_id=proc.cohort_id, is_active=True)
                .order_by(CotejoRequirement.order_index, CotejoRequirement.id)
                .all())
    cumplidos = {
        f.requirement_id: f for f in
        db.query(RequirementFulfillment).filter_by(process_id=process_id).all()
    }
    # Diccionarios PLANOS, no objetos ORM: `process_detail` renderiza DESPUES de
    # su `db.close()` y un atributo expirado sobre una instancia desanclada
    # lanzaria `DetachedInstanceError` (misma razon que `_checklist_ctx` del
    # alumno en `pages/student.py`).
    requisitos = []
    for r in req_rows:
        ful = cumplidos.get(r.id)
        requisitos.append({
            "id": r.id,
            "icon": r.icon or "check2-square",
            "label": r.label,
            "hint": r.hint or "",
            "required": bool(r.is_required),
            "auto_source": r.auto_source,
            "done": bool(ful is not None and ful.status in DONE_STATUSES),
            "status": (ful.status if ful else None),
            "source": (ful.source if ful else None),
            "note": (ful.note if ful else None),
            "when": (f"{ful.fulfilled_at:%d/%m/%Y}" if ful and ful.fulfilled_at else None),
        })

    # Los controles se pintan solo para quien puede usarlos: un boton que
    # contesta 403 es peor que no estar. Mismo patron que `cohort_detail`.
    can_mark_reqs = False
    # Arreglo A2 (revision final 2026-09-21): mismo criterio para «Mover de
    # fase» (_exp_shell.html) y «Aprobar/Rechazar Formato B» (_exp_phase.html,
    # fase 3) -- el spec §10 paso 4 exige que la jefatura de la Division
    # (titulatec_titulaciones, recortada a supervision) ya NO vea estos
    # botones tras perder el permiso, y hoy los veia igual porque el template
    # solo miraba el ESTADO del dato, nunca el permiso del actor.
    # `can_dictaminar_fase` es OR de approve_phase/reject_phase porque el
    # modal «Mover de fase» ofrece las DOS acciones (`process_detail.html`,
    # botones «Aprobar fase»/«Rechazar fase» del mismo `#exp-modal-fase`): con
    # solo uno de los dos permisos, al menos una mitad del modal SI funciona.
    can_dictaminar_fase = False
    can_dictaminar_fb = False
    can_revoke = False
    can_register_prior = False
    # Pestañas que el actor puede abrir (spec 2026-10-07 §1.2): decide qué
    # enlaces a otras pestañas se pintan y a dónde regresa «Regresar» sin
    # `from`. Sin actor, ninguno (fail-closed, como los `can_*`).
    abiertas = None
    if user_id is not None:
        from itcj2.core.services.authz_cache import cached_perms
        _user_perms = cached_perms(db, user_id, "titulatec")
        abiertas = _tabs_abiertas(_user_perms)
        # Sobre una inscripción revocada el checklist queda de solo lectura:
        # acreditarle un requisito ya no mueve nada.
        can_mark_reqs = ("titulatec.process.api.requirement.mark" in _user_perms
                         and proc.status != "cancelled")
        can_dictaminar_fase = bool(_user_perms & {
            "titulatec.process.api.approve_phase", "titulatec.process.api.reject_phase",
        })
        can_dictaminar_fb = bool(_user_perms & {
            "titulatec.format_b.api.approve", "titulatec.format_b.api.reject",
        })
        # «Revocar inscripción»: mismo permiso que exige `process_cancel`, y
        # solo sobre lo que `ProcessService.cancel` acepta revocar.
        can_revoke = ("titulatec.process.api.cancel" in _user_perms
                      and proc.status in ProcessService.REVOCABLE_STATUSES)
        # Respaldo «Constancia previa…» / «Deshacer» (D9, spec 2026-10-01-
        # titulatec-biblioteca-caja-design.md §4.9): mismo criterio que
        # `can_mark_reqs` -sobre una inscripción revocada no hay nada que
        # registrar-, pero con el permiso propio de SE
        # (`titulatec.library_clearance.api.prior`, ya otorgado por el DML).
        can_register_prior = ("titulatec.library_clearance.api.prior" in _user_perms
                              and proc.status != "cancelled")

    # La revocación vigente (motivo, cuándo, quién). Dict plano: se renderiza
    # después del `db.close()` de la ruta.
    revocada = ProcessService.cancellation_info(db, proc)
    if revocada is not None:
        quien = db.get(User, revocada["actor_id"]) if revocada["actor_id"] else None
        revocada = {"reason": revocada["reason"],
                    "when": _fecha_larga(revocada["at"]),
                    "actor": quien.full_name if quien else None}

    appt = AppointmentService.get_for_process(db, process_id)

    # Estatus de la solicitud de liberación de GTV para la encuesta de
    # egresados (D3, spec 2026-09-15-titulatec-liberacion-gtv §6.2). Dict
    # plano de `summary_for_process`, MISMA fuente que el panel de atender
    # (`pages/appointments.py::_detail_ctx`): el expediente también renderiza
    # DESPUÉS de su `db.close()`.
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService
    survey = SurveyReviewService.summary_for_process(db, process_id)

    # Mismo trato para el no adeudo de biblioteca (D9, Tarea 11): dict plano
    # de `LibraryClearanceService.summary_for_process`, MISMA fuente que el
    # panel de atender (`pages/appointments.py::_detail_ctx`). `format_amount`
    # va al contexto -no como texto ya formado- porque la fila también pinta
    # el desglose del recibo/certificado, que varía según `via`.
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService, format_amount,
    )
    library = LibraryClearanceService.summary_for_process(db, process_id)

    # Celda «Constancia» de las dos filas (Ruling R14, revisión final de
    # `2026-10-02-titulatec-constancias-y-pendientes-design.md` §3.4): UNA
    # llamada a `print_status_map` para encuesta y no adeudo juntos -a lo más
    # 2 consultas por vista, invariante 2- con los refs que EXISTAN (sin
    # solicitud o sin fila no se pide nada), colgada como `certificate` en
    # cada resumen (`None` si no aplica). Los `summary_for_process` no la
    # consultan: también los usan el tablero del egresado, «Mi cita» y las
    # páginas públicas. MISMO bloque que `pages/appointments.py::_detail_ctx`.
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    ref_encuesta = SurveyReviewService.certificate_ref(survey["review_id"])
    ref_biblioteca = LibraryClearanceService.certificate_ref(library["clearance_id"])
    impresion = CertificateService.print_status_map(
        db, [ref for ref in (ref_encuesta, ref_biblioteca) if ref])
    survey["certificate"] = impresion.get(ref_encuesta)
    library["certificate"] = impresion.get(ref_biblioteca)

    # ---- bitácora de correos al egresado (spec 2026-09-28 §7, D11) ----
    #
    # Solo lectura, sin reenviar. UNA consulta (`StudentMail.history`, ya
    # ordenada `created_at DESC, id DESC`) y una entrada por CORREO, no por
    # aviso (ruling 21): `_bitacora_correos` junta los avisos de un grupo que
    # salieron (o se quedaron) juntos. Dicts PLANOS por la misma razón que
    # `revocada`/`otros_eventos` arriba.
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    correos = _bitacora_correos(StudentMail.history(db, process_id))

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
        # Perfil ya resuelto arriba -- alimenta `track_pill` junto a la
        # carrera en `_exp_shell.html:86`.
        "track": track,
        "modality_name": modality.name if modality else None,
        "current_phase": current,
        "progress_pct": max(0, min(100, round(current / max_phase * 100))),
        "fases": fases,
        "open_phase": open_phase,
        "back": _back_ctx(back_raw, abiertas),
        # `can_open.cohorts` / `.documents` / `.appointments`: los enlaces del
        # expediente a esas pestañas (`_exp_phase.html`) solo se pintan si la
        # guarda REAL de la ruta destino deja pasar al actor (`_TAB_PERMS`).
        "can_open": abiertas or dict.fromkeys(_TAB_PERMS, False),
        "docs": docs,
        "doc_abierto": abierto["type_code"] if abierto else None,
        "doc_src": abierto["view_url"] if abierto else None,
        "appt": ({"status": appt.status,
                  # Helper "cuándo" (spec 2026-09-29-titulatec-cotejo-
                  # espacios-design.md §6, D11): una reserva sin horario
                  # anuncia su rango, no una hora que nunca tuvo.
                  "scheduled_label": AppointmentService.when(appt)["label"],
                  "location": appt.location, "note": appt.note,
                  "change_request": appt.change_request,
                  "change_requested_at": _fecha_larga(appt.change_requested_at)}
                 if appt else None),
        "formato_b": formato_b,
        "otros_eventos": sin_fase,
        "requisitos": requisitos,
        "can_mark_reqs": can_mark_reqs,
        "can_dictaminar_fase": can_dictaminar_fase,
        "can_dictaminar_fb": can_dictaminar_fb,
        "can_revoke": can_revoke,
        "revocada": revocada,
        "survey": survey,
        "library": library,
        "can_register_prior": can_register_prior,
        "format_amount": format_amount,
        "correos": correos,
    }


def _summary_ctx(db, process_id: int, *, abiertas: dict, back_raw=None) -> dict:
    """El expediente RESUMIDO (spec 2026-10-07 §7, D7): Departamento de Titulación.

    Cabecera (alumno, número de control, carrera, convocatoria, modalidad o «Sin
    elegir», correo) + las fases ANTERIORES al corte a T-soft
    (`PhaseService._handoff_phase()`, hoy 3) con número, nombre, estado y fecha.
    Las fases desde el corte NO se piden. No se consulta NADA del desglose
    (documentos, eventos, cita, requisitos, biblioteca, encuesta, correos): lo
    que no se lee no se puede filtrar por un descuido de plantilla.

    El correo es el PERSONAL con la resolución de `StudentMail.contact_email` y,
    sin él, el institucional: lo mismo que pinta la bandeja Liberados
    (`HandoffService`). «Regresar» solo acepta un `from` de Liberados (con sus
    filtros); cualquier otro cae al regreso por omisión.

    Dicts PLANOS: la ruta renderiza después de su `db.close()`.
    """
    from itcj2.core.models.program import Program
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import (
        Cohort, Modality, PhaseDefinition, ProcessPhase, TitulationProcess,
    )
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.student_mail import StudentMail

    proc = db.get(TitulationProcess, process_id)
    student = db.get(User, proc.student_id)
    cohort = db.get(Cohort, proc.cohort_id)
    modality = db.get(Modality, proc.modality_id) if proc.modality_id else None
    program = db.get(Program, proc.program_id) if proc.program_id else None
    correo = (StudentMail.contact_email(db, proc)
              or ((student.email or "").strip() if student else "") or None)

    corte = PhaseService._handoff_phase()
    pdefs = (db.query(PhaseDefinition)
             .filter(PhaseDefinition.is_active.is_(True), PhaseDefinition.number < corte)
             .order_by(PhaseDefinition.order_index).all())
    filas = {ph.phase_number: ph for ph in
             db.query(ProcessPhase).filter(ProcessPhase.process_id == process_id,
                                           ProcessPhase.phase_number < corte).all()}
    fases = []
    for pd in pdefs:
        ph = filas.get(pd.number)
        if ph is not None and ph.completed_at:
            fecha = f"Se cerró el {_fecha_larga(ph.completed_at)}"
        elif ph is not None and ph.started_at:
            fecha = f"Empezó el {_fecha_larga(ph.started_at)}"
        else:
            fecha = ""
        fases.append({"number": pd.number, "name": pd.name,
                      "status": ph.status if ph else "pending", "fecha": fecha})

    desde_liberados = (back_raw or "").strip().startswith(_BACK_LIBERADOS)
    return {
        "process": {"id": proc.id, "folio": proc.folio, "status": proc.status},
        "student": {"name": student.full_name if student else "—",
                    "control": student.control_number if student else "—"},
        "email": correo,
        "program_name": program.name if program else None,
        "cohort_name": cohort.name if cohort else None,
        "modality_name": modality.name if modality else None,
        "fases": fases,
        "back": _back_ctx(back_raw if desde_liberados else None, abiertas),
    }


def _proc_universe(db, *, user_id, status="", q=None):
    """PASADA 1 de Procesos: filas ligeras del universo + KPIs.

    Una sola consulta: los procesos en alcance (`officer_programs`, ANTES de
    contar) y del `status` pedido, con el `started_at` de su fase ACTUAL por
    outer join (`uq_titulatec_phase_process_number` garantiza una fila como
    mucho), en orden `created_at DESC, id DESC`. Con `q`, una consulta más
    devuelve los ids que casan (`process_search`, que exige el join a `User`).

    Devuelve `(ligeras, kpis)`:

    * `ligeras` -- dicts `{"id", "created_at", "status", "current_phase",
      "student_id", "program_id", "started_at_fase", "idle_days", "idle_level"}`
      (+ `folio` y `modality_id`, que viajan de la misma fila para no volver a
      leerlas en la pasada 2) del universo filtrado por estado y `q` (la fase la aplica `_proc_ctx`).
      SIN el filtro «atorados»: ese lo aplica quien llama sobre `idle_level`.
    * `kpis` -- con la lógica de siempre, sobre el universo filtrado por alcance
      y `status` (como hoy: los KPIs son también los filtros de estado) pero
      NUNCA por `q`, `phase`, `stuck` ni la página. `n_stuck` cuenta ese mismo
      universo.
    """
    from datetime import datetime

    from sqlalchemy import and_

    from itcj2.apps.titulatec.models import ProcessPhase, TitulationProcess
    from itcj2.apps.titulatec.services.process_service import process_search
    from itcj2.apps.titulatec.services.scope_service import officer_programs
    from itcj2.config import get_settings
    from itcj2.core.models.user import User

    settings = get_settings()
    warn_days = settings.TITULATEC_IDLE_WARN_DAYS
    crit_days = settings.TITULATEC_IDLE_CRIT_DAYS
    kpis = {"total": 0, "active": 0, "completed": 0, "on_hold": 0,
            "cancelled": 0, "pct_completed": 0, "n_stuck": 0}

    scope = officer_programs(db, user_id)
    if scope != "ALL" and not scope:
        return [], kpis

    def _alcance(query):
        if scope != "ALL":
            query = query.filter(TitulationProcess.program_id.in_(scope))
        if status:
            query = query.filter(TitulationProcess.status == status)
        return query

    TP = TitulationProcess
    base = _alcance(
        db.query(TP.id, TP.created_at, TP.status, TP.current_phase, TP.student_id,
                 TP.program_id, TP.folio, TP.modality_id, TP.updated_at,
                 ProcessPhase.started_at)
        .outerjoin(ProcessPhase, and_(ProcessPhase.process_id == TP.id,
                                      ProcessPhase.phase_number == TP.current_phase))
    ).order_by(TP.created_at.desc(), TP.id.desc())

    now = datetime.now()
    universo = []
    for (pid, created_at, st, current_phase, student_id, program_id, folio,
         modality_id, updated_at, started_at) in base.all():
        since = started_at or updated_at
        idle_days = max(0, (now - since).days) if since else 0
        idle_level = ("crit" if idle_days >= crit_days
                      else "warn" if idle_days >= warn_days else "ok")
        # Una inscripción revocada no está «atorada»: ya no espera nada.
        if st == "cancelled":
            idle_level = "ok"
        universo.append({
            "id": pid, "created_at": created_at, "status": st,
            "current_phase": current_phase, "student_id": student_id,
            "program_id": program_id, "started_at_fase": started_at,
            "idle_days": idle_days, "idle_level": idle_level,
            "folio": folio, "modality_id": modality_id,
        })

    # KPIs. Una inscripción revocada no es un alumno en proceso: fuera del total
    # y del porcentaje, como en el Resumen de la convocatoria
    # (`_cohort_summary_ctx`), salvo que se pidan las revocadas; se cuentan
    # aparte en `cancelled`.
    vivos = (universo if status == "cancelled"
             else [r for r in universo if r["status"] != "cancelled"])
    kpis["total"] = len(vivos)
    kpis["cancelled"] = sum(1 for r in universo if r["status"] == "cancelled")
    for r in vivos:
        if r["status"] in ("active", "completed", "on_hold"):
            kpis[r["status"]] += 1
    if kpis["total"]:
        kpis["pct_completed"] = round(kpis["completed"] / kpis["total"] * 100)
    kpis["n_stuck"] = sum(1 for r in universo if r["idle_level"] == "crit")

    filtradas = universo
    pred = process_search(q)
    if pred is not None:
        casan = {pid for (pid,) in _alcance(
            db.query(TP.id).outerjoin(User, User.id == TP.student_id)).filter(pred)}
        filtradas = [r for r in filtradas if r["id"] in casan]
    return filtradas, kpis


def _proc_present(db, ligeras, *, phase_names, max_phase):
    """PASADA 2 de Procesos: arma la fila completa SOLO de las visibles.

    Alumnos, carreras y modalidades en lote (una consulta cada uno, solo si hay
    ids): quita el `db.get(User)` / `db.get(Program)` por fila de antes.
    """
    from itcj2.apps.titulatec.models import Modality
    from itcj2.core.models.program import Program
    from itcj2.core.models.user import User

    if not ligeras:
        return []
    user_ids = {r["student_id"] for r in ligeras}
    prog_ids = {r["program_id"] for r in ligeras if r["program_id"]}
    mod_ids = {r["modality_id"] for r in ligeras if r["modality_id"]}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids))}
    progs = ({p.id: p.name for p in db.query(Program).filter(Program.id.in_(prog_ids))}
             if prog_ids else {})
    mods = ({m.id: m.name for m in db.query(Modality).filter(Modality.id.in_(mod_ids))}
            if mod_ids else {})

    rows = []
    for r in ligeras:
        u = users.get(r["student_id"])
        phase = r["current_phase"]
        rows.append({
            "id": r["id"], "folio": r["folio"],
            "student": u.full_name if u else "—",
            "control": u.control_number if u else "—",
            "program": progs.get(r["program_id"], "—"),
            "modality": mods.get(r["modality_id"], "—"),
            "phase": phase, "phase_name": phase_names.get(phase, ""),
            "status": r["status"],
            "idle_days": r["idle_days"], "idle_level": r["idle_level"],
            "progress_pct": max(0, min(100, round(phase / max_phase * 100))),
        })
    return rows


def _proc_url(view, status, stuck, q, phase=None) -> str:
    """URL canónica de la bandeja con sus filtros (para `href`/`hx-get`)."""
    from urllib.parse import urlencode

    pares = [("view", view)]
    if status:
        pares.append(("status", status))
    if stuck:
        pares.append(("stuck", 1))
    if phase is not None:
        pares.append(("phase", phase))
    if q:
        pares.append(("q", q))
    return "/titulatec/admin/processes?" + urlencode(pares)


def _proc_ctx(db, *, user_id, status="", view="table", stuck=0, q=None, phase=None,
              page=1, per_page: int = PAGE_SIZE) -> dict:
    """Contexto completo de la bandeja de Procesos (dos pasadas).

    Tabla: el universo filtrado (estado, `q`, «atorados», `phase`) se pagina en
    Python (`paginate_list`, orden `created_at DESC, id DESC`) y solo la página
    pasa a la pasada 2.

    Tablero / funnel: el universo filtrado SIN `phase` (cada columna YA es una
    fase) se agrupa por fase actual; cada columna conserva su conteo real y
    presenta como mucho `per_page` tarjetas (las más recientes), con
    `table_url` = «Ver las N en tabla» (`?view=table&phase=N` + filtros
    vigentes). Sin las revocadas (salvo que se pidan): en el tablero se
    leerían como alumnos parados en su fase.
    """
    from itcj2.apps.titulatec.models import PhaseDefinition
    from itcj2.apps.titulatec.utils.paging import normalize_q, paginate_list
    from itcj2.config import get_settings

    settings = get_settings()
    view = "board" if view == "board" else "table"
    stuck = 1 if stuck else 0
    q = normalize_q(q)

    universo, kpis = _proc_universe(db, user_id=user_id, status=status, q=q)
    if stuck:
        universo = [r for r in universo if r["idle_level"] == "crit"]

    todas = db.query(PhaseDefinition).order_by(PhaseDefinition.order_index).all()
    phase_names = {d.number: d.name for d in todas}
    phase_defs = [d for d in todas if d.is_active]
    max_phase = max((d.number for d in phase_defs), default=0) or 1

    buckets: dict[int, list] = {}
    for r in universo:
        if r["status"] == "cancelled" and status != "cancelled":
            continue
        buckets.setdefault(r["current_phase"], []).append(r)

    columns = []
    for d in phase_defs:
        cards = buckets.get(d.number, [])
        columns.append({
            "phase": d.number, "label": d.name, "count": len(cards),
            "n_stuck": sum(1 for c in cards if c["idle_level"] == "crit"),
            "rows": cards[:per_page] if view == "board" else [],
            "more": len(cards) > per_page,
            "table_url": _proc_url("table", status, stuck, q, phase=d.number),
        })

    if view == "board":
        visibles = [r for c in columns for r in c["rows"]]
        presentadas = {r["id"]: r for r in _proc_present(
            db, visibles, phase_names=phase_names, max_phase=max_phase)}
        for c in columns:
            c["rows"] = [presentadas[r["id"]] for r in c["rows"]]
        pagina, rows = None, []
    else:
        en_fase = (universo if phase is None
                   else [r for r in universo if r["current_phase"] == phase])
        pagina = paginate_list(en_fase, page, per_page)
        rows = _proc_present(db, pagina.items, phase_names=phase_names,
                             max_phase=max_phase)

    return {
        "rows": rows, "page": pagina, "columns": columns, "kpis": kpis,
        "status": status, "view": view, "stuck": stuck, "q": q or "", "phase": phase,
        "idle_warn": settings.TITULATEC_IDLE_WARN_DAYS,
        "idle_crit": settings.TITULATEC_IDLE_CRIT_DAYS,
    }


@router.get("/processes", name="titulatec.pages.admin.processes")
def processes(
    request: Request,
    status: str = "",
    view: str = "table",
    stuck: str = "",
    q: str = "",
    phase: str = "",
    page: str = "",
    user: dict = Depends(require_page_app("titulatec", perms=_PROCESS_LIST_PERMS)),
):
    """Bandeja de procesos (tabla paginada o tablero kanban acotado) con KPIs,
    funnel de fases, señal de atoro (días sin moverse) y búsqueda en servidor.

    Guarda propia (`_PROCESS_LIST_PERMS`, spec 2026-10-07 §1.2): el expediente
    sigue con `_PROCESS_VIEW_PERMS`, pero la lista no se abre con
    `process.page.detail`/`read.all`/`dashboard.*` solos.

    `stuck`, `phase` y `page` llegan como texto y se interpretan con
    tolerancia (vacío / basura = sin filtro / página 1): el formulario de
    filtros los manda siempre, a veces vacíos.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.utils.paging import parse_page

    try:
        stuck_on = 1 if int(stuck or 0) else 0
    except ValueError:
        stuck_on = 0
    try:
        fase = int(phase) if phase.strip() else None
    except ValueError:
        fase = None

    db = SessionLocal()
    try:
        ctx = _proc_ctx(db, user_id=int(user["sub"]), status=status, view=view,
                        stuck=stuck_on, q=q, phase=fase, page=parse_page(page))
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/processes.html", ctx)


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
def process_detail(
    process_id: int,
    request: Request,
    # La suma explícita (no `_PROCESS_VIEW_PERMS`, que vale lo mismo) para que
    # `test_permissions_contract.py` resuelva los códigos por AST.
    user: dict = Depends(require_page_app(
        "titulatec", perms=_PROCESS_FULL_VIEW_PERMS + _PROCESS_SUMMARY_PERMS)),
):
    """El expediente del alumno: cabecera + acordeón de las 9 fases con su historial.

    Con `process.page.summary` y sin ningún código de vista completa
    (`_vista_completa`), la vista RESUMIDA (D7): `_summary_ctx` +
    `admin/process_summary.html`, sin desglose."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope
    from itcj2.core.services.authz_cache import cached_perms
    db = SessionLocal()
    try:
        # 404 uniforme: "no existe" y "no es de tus carreras" son indistinguibles.
        # El guard ya cubre el proceso inexistente, asi que `_detail_ctx` no
        # puede devolver None a partir de aqui.
        assert_process_in_scope(db, int(user["sub"]), process_id)
        params = _exp_params(request)
        perms = cached_perms(db, int(user["sub"]), "titulatec")
        if _vista_completa(perms):
            plantilla = "titulatec/admin/process_detail.html"
            ctx = _detail_ctx(db, process_id, user_id=int(user["sub"]), **params)
            ctx["zona"] = _exp_query(params)
        else:
            plantilla = "titulatec/admin/process_summary.html"
            ctx = _summary_ctx(db, process_id, abiertas=_tabs_abiertas(perms),
                               back_raw=params["back_raw"])
    finally:
        db.close()
    return render_titulatec(request, plantilla, ctx)


def _render_detail_body(request, db, process_id, user_id: int | None = None):
    """El cuerpo del expediente re-renderizado tras una acción (swap HTMX)."""
    params = _exp_params(request)
    ctx = _detail_ctx(db, process_id, user_id=user_id, **params)
    ctx["zona"] = _exp_query(params)
    return render_titulatec(request, "titulatec/partials/processes/_exp_shell.html", ctx)


@router.post("/processes/{process_id}/format-b/review", name="titulatec.pages.admin.fb_review")
async def fb_review(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=[
        "titulatec.format_b.api.approve", "titulatec.format_b.api.reject"])),
):
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_fb_review, process_id=process_id, request=request, user=user, form=form)


def _cuerpo_fb_review(process_id, request, user, form):
    """Cuerpo síncrono de `fb_review`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import FormatB
    from itcj2.apps.titulatec.services.format_b_service import FormatBService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    action = form.get("action")
    note = form.get("note")
    status = "approved" if action == "approve" else "rejected"
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, int(user["sub"]), process_id)
        _exigir_vista_completa(db, int(user["sub"]))   # resumen -> 403 (D7)
        fb = db.get(FormatB, process_id)
        if fb:
            try:
                FormatBService.review(db, fb, proc, status=status, note=note,
                                      reviewer_id=int(user["sub"]))
            except ValueError as exc:
                return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        return _render_detail_body(request, db, process_id, int(user["sub"]))
    finally:
        db.close()


@router.post("/processes/{process_id}/phase/{n}/approve", name="titulatec.pages.admin.phase_approve")
def phase_approve(
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
        _exigir_vista_completa(db, int(user["sub"]))   # resumen -> 403 (D7)
        try:
            PhaseService.approve_phase(db, proc, n, int(user["sub"]))
        except ValueError as exc:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        return _render_detail_body(request, db, process_id, int(user["sub"]))
    finally:
        db.close()


@router.post("/processes/{process_id}/phase/{n}/reject", name="titulatec.pages.admin.phase_reject")
async def phase_reject(
    process_id: int,
    request: Request,
    n: int = Path(ge=0),
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.process.api.reject_phase"])),
):
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_phase_reject, process_id=process_id, request=request, n=n, user=user, form=form)


def _cuerpo_phase_reject(process_id, request, n, user, form):
    """Cuerpo síncrono de `phase_reject`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

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
        _exigir_vista_completa(db, int(user["sub"]))   # resumen -> 403 (D7)
        try:
            PhaseService.reject_phase(db, proc, n, int(user["sub"]), reason)
        except ValueError as exc:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        return _render_detail_body(request, db, process_id, int(user["sub"]))
    finally:
        db.close()


@router.post("/processes/{process_id}/cancelar", name="titulatec.pages.admin.process_cancel")
async def process_cancel(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.process.api.cancel"])),
):
    """«Revocar inscripción» desde el expediente (spec 2026-09-25 §3.6).

    Motivo obligatorio: es lo que el alumno lee en su dashboard. Alcance por
    carrera con el mismo guard que el resto de rutas con `{process_id}` (404
    liso fuera de alcance). Devuelve el expediente re-renderizado, como
    aprobar/rechazar fase; los rechazos de `ProcessService.cancel` (ya
    revocada, completada) son 400 + `X-Tt-Error`.
    """
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_process_cancel, process_id=process_id, request=request, user=user, form=form)


def _cuerpo_process_cancel(process_id, request, user, form):
    """Cuerpo síncrono de `process_cancel`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.process_service import ProcessService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    reason = (form.get("reason") or "").strip()
    if not reason:
        return Response(status_code=400, headers={
            "X-Tt-Error": _hdr("Escribe el motivo de la revocación: es lo que el alumno lee.")})
    db = SessionLocal()
    try:
        assert_process_in_scope(db, int(user["sub"]), process_id)
        _exigir_vista_completa(db, int(user["sub"]))   # resumen -> 403 (D7)
        ok, msg = ProcessService.cancel(db, process_id, reason=reason,
                                        actor_id=int(user["sub"]))
        if not ok:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(msg)})
        return _render_detail_body(request, db, process_id, int(user["sub"]))
    finally:
        db.close()


@router.post("/processes/{process_id}/requisitos/{rid}",
             name="titulatec.pages.admin.process_requirement")
async def process_requirement(
    process_id: int,
    rid: int,
    request: Request,
    user: dict = Depends(require_page_app(
        "titulatec", perms=["titulatec.process.api.requirement.mark"])),
):
    """El oficial marca, dispensa o desmarca un requisito de cotejo del alumno.

    `action` ∈ ``mark`` | ``waive`` | ``unmark``; `note` es libre y es lo que se
    guarda como justificación de la dispensa.

    **Permiso NUEVO** (`titulatec.process.api.requirement.mark`). El
    `titulatec.process.api.review` que se había supuesto NO existe en el repo:
    como `require_page_app` resuelve el código contra `core_permissions` y no
    tiene bypass de admin global, exigirlo habría dado 403 a todo el mundo y
    dejado la fase 2 permanentemente inaprobable. Se otorga a
    `titulatec_school_services` y a `titulatec_school_services_head`: quien usa
    el checklist en ventanilla es el encargado operativo, no solo la jefa.

    Quién acreditó queda en `checked_by_id`, que es el campo donde `fulfill`
    escribe la identidad del oficial.

    Los requisitos con `auto_source` son de SOLO LECTURA aquí: los acredita el
    sistema (la encuesta de egresados, que libera GTV, y el no adeudo de
    biblioteca, que liberan Biblioteca y Caja) y marcarlos a mano rompería la
    trazabilidad de `external_ref`.

    Devuelve el cuerpo del expediente re-renderizado, igual que aprobar/rechazar
    fase: el checklist se pinta en `_exp_phase.html` (rama de la fase 2), que
    `_exp_shell.html` incluye por fase, y el swap es del shell entero, no de la
    fila.
    """
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_process_requirement, process_id=process_id, rid=rid, request=request, user=user,
        form=form)


def _cuerpo_process_requirement(process_id, rid, request, user, form):
    """Cuerpo síncrono de `process_requirement`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import CotejoRequirement
    from itcj2.apps.titulatec.services.requirement_service import RequirementService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    accion = (form.get("action") or "mark").strip()
    # `note` AUSENTE = «no lo mandes, conserva lo que haya»; `note` VACÍO =
    # «borra la nota». La distinción es deliberada: `RequirementService.fulfill`
    # lee `None` como "el llamador no lo manda" y conserva el valor anterior,
    # así que normalizar el campo vacío a `None` dejaría al oficial sin forma de
    # corregir una nota equivocada salvo desmarcando y volviendo a marcar. El
    # formulario del checklist SIEMPRE envía el input, así que vaciarlo borra.
    nota = form["note"].strip() if "note" in form else None

    db = SessionLocal()
    try:
        # El guard sustituye al `db.get` + 404 y ademas comprueba que el proceso
        # sea de una carrera del usuario. 404 uniforme, sin `X-Tt-Error`: el id
        # es secuencial y un 403 convertiria la ruta en un contador del padron.
        proc = assert_process_in_scope(db, int(user["sub"]), process_id)
        _exigir_vista_completa(db, int(user["sub"]))   # resumen -> 403 (D7)

        req = (db.query(CotejoRequirement)
               .filter_by(id=rid, cohort_id=proc.cohort_id).first())
        if req is None:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(
                "Ese requisito no es de la convocatoria del alumno.")})
        if req.auto_source:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(
                "Ese requisito lo acredita el sistema; no se marca a mano.")})

        if accion == "unmark":
            RequirementService.unfulfill(db, process_id, rid,
                                         actor_id=int(user["sub"]))
        else:
            RequirementService.fulfill(
                db, process_id, rid, source="officer",
                checked_by_id=int(user["sub"]), note=nota,
                status=("waived" if accion == "waive" else "fulfilled"),
            )
        return _render_detail_body(request, db, process_id, int(user["sub"]))
    finally:
        db.close()


# ===========================================================================
# Respaldo «Constancia previa…» / «Deshacer» del no adeudo de biblioteca (D9)
# ===========================================================================
# Servicios Escolares, desde el expediente (gemelas en `pages/appointments.py`
# para el panel de atender). Van por `{process_id}` con `assert_process_in_
# scope` como PRIMERA sentencia del `try` (censo de `test_scope_guard.py`,
# spec §5 invariante 6) -- a diferencia de las de Biblioteca
# (`pages/library_admin.py`), que van por `clearance_id` y ven todo.
#
# `LibraryClearanceService.for_process_locked` resuelve `process_id` ->
# `LibraryClearance` (la abre `pending` si el proceso no tenía fila: alta
# durante el blue/green) y la deja bloqueada; `register_prior`/`undo_prior`
# vuelven a bloquearla por su `clearance_id` -misma transacción, el mismo
# lock no se disputa a sí mismo- antes de aplicar la transición de verdad.

@router.post("/processes/{process_id}/no-adeudo-previo",
             name="titulatec.pages.admin.process_library_prior")
async def process_library_prior(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app(
        "titulatec", perms=["titulatec.library_clearance.api.prior"])),
):
    """SE registra, desde el expediente, que el egresado YA trae su
    constancia previa de no adeudo (D9): `pending`/`awaiting_payment` ->
    `cleared/prior`, sin pasar por Caja. Respaldo para quien no tiene cita
    todavía; Biblioteca tiene el mismo botón en su propia bandeja
    (`pages/library_admin.py::prior`)."""
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_process_library_prior, process_id=process_id, request=request, user=user,
        form=form)


def _cuerpo_process_library_prior(process_id, request, user, form):
    """Cuerpo síncrono de `process_library_prior`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope
    from itcj2.apps.titulatec.utils.form_dates import parse_issued_on

    note = form.get("note") or None
    db = SessionLocal()
    try:
        assert_process_in_scope(db, int(user["sub"]), process_id)
        _exigir_vista_completa(db, int(user["sub"]))   # resumen -> 403 (D7)
        try:
            issued_on = parse_issued_on(form.get("issued_on"))
            clearance = LibraryClearanceService.for_process_locked(db, process_id)
            LibraryClearanceService.register_prior(
                db, clearance.id, int(user["sub"]), issued_on=issued_on, note=note,
                by="school_services")
        except LookupError:
            return Response(status_code=404)
        except ValueError as exc:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        return _render_detail_body(request, db, process_id, int(user["sub"]))
    finally:
        db.close()


@router.post("/processes/{process_id}/no-adeudo-previo/deshacer",
             name="titulatec.pages.admin.process_library_prior_undo")
async def process_library_prior_undo(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app(
        "titulatec", perms=["titulatec.library_clearance.api.prior"])),
):
    """Deshace la constancia previa (motivo obligatorio): `cleared/prior` ->
    `pending`. Solo si la fase 2 todavía no está aprobada
    (`LibraryClearanceService.can_revert`, parte del dict de
    `summary_for_process` que ya trae la plantilla)."""
    form = dict(await request.form())
    return await run_in_threadpool(
        _cuerpo_process_library_prior_undo, process_id=process_id, request=request, user=user,
        form=form)


def _cuerpo_process_library_prior_undo(process_id, request, user, form):
    """Cuerpo síncrono de `process_library_prior_undo`: corre en el threadpool, no en el event loop."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    reason = form.get("reason") or ""
    db = SessionLocal()
    try:
        assert_process_in_scope(db, int(user["sub"]), process_id)
        _exigir_vista_completa(db, int(user["sub"]))   # resumen -> 403 (D7)
        try:
            clearance = LibraryClearanceService.for_process_locked(db, process_id)
            LibraryClearanceService.undo_prior(db, clearance.id, int(user["sub"]), reason)
        except LookupError:
            return Response(status_code=404)
        except ValueError as exc:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        return _render_detail_body(request, db, process_id, int(user["sub"]))
    finally:
        db.close()
