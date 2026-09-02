"""Agenda de Citas de cotejo (fase 2) — Servicios Escolares.

Una sola vista con TRES zonas que viven a la vez en `#appt-shell`:

    A · agenda      — el CALENDARIO del mes (vista principal), o la lista de un
                      dia concreto (`?date=`), o la lista filtrada completa
                      (`?view=list`).
    B · por agendar — SIEMPRE visible, con contador. Es la cola de trabajo del
                      encargado; no la filtra la barra de filtros de la zona A.
    C · detalle     — la ficha del alumno seleccionado (`?selected=`), al lado de
                      la zona A. Solo se abre uno.

Decision del usuario (2026-09-02): el calendario es la vista principal, "Por
agendar" queda fijo a su lado (debajo en movil) y elegir un alumno abre SOLO ese
en un panel de detalle junto a la lista del dia — sin saltar a otra pestana. Se
elimino el boton "Del dia" del segmento: sin fecha aterrizaba en HOY, que fuera
de la semana de cotejo son 0 citas, o sea un callejon sin salida. Al dia se llega
picando una celda del calendario, y dentro del dia hay un selector de fecha.

Patron HTMX: cada control hace `hx-get` sobre `/body` y swappea `#appt-shell`
entero con `morph:outerHTML` (Idiomorph), de modo que lo que no cambia no se
mueve. `hx-push-url` apunta a la URL de PAGINA (no a `/body`), asi que F5 y el
boton Atras reconstruyen el estado exacto.

Alcance por carrera: `officer_programs` se resuelve UNA vez por peticion y se
pasa a las CUATRO consultas de listado (`list_appointments`, `list_for_day`,
`counts_by_day`, `list_pending_processes`) mas `agenda_process_ids`. Los defaults
de esos servicios son ABIERTOS (`allowed_program_ids=None` = sin restriccion),
asi que olvidar uno filtra de menos EN SILENCIO: lo cubre
tests/fastapi/titulatec/test_appointments_scope_day.py.
"""
import logging
from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response

from itcj2.dependencies import require_page_app
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.appointments")

router = APIRouter(prefix="/admin/appointments", tags=["titulatec-pages-appointments"])

PAGE_URL = "/titulatec/admin/appointments"
BODY_URL = "/titulatec/admin/appointments/body"

_INITIAL_DOC_TYPES = ["birth_certificate", "high_school_cert", "curp"]

_MONTHS_ES = ["", "ene", "feb", "mar", "abr", "may", "jun",
              "jul", "ago", "sep", "oct", "nov", "dic"]

# Rotulo del calendario. `calendar.month_name` sale en el locale del proceso, que
# en el contenedor es C -> "September 2026" en una UI en espanol.
_MONTHS_ES_FULL = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                   "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

_WEEKDAYS_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]

# Permisos para ver/gestionar la agenda (servicios escolares + admin).
_VIEW_PERMS = ["titulatec.appointment.page.list", "titulatec.dashboard.school_services",
               "titulatec.dashboard.admin"]


def _label(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return f"{dt.day:02d} {_MONTHS_ES[dt.month]} {dt.year} · {dt:%H:%M}"


def _day_label(d) -> str:
    """'07 sep 2026' — cabecera de la vista de dia."""
    return f"{d.day:02d} {_MONTHS_ES[d.month]} {d.year}" if d else "—"


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


def _parse_date(raw: str | None):
    """'YYYY-MM-DD' -> date, o None. Un valor basura NO revienta la pagina."""
    from datetime import datetime as _dt
    if not raw:
        return None
    try:
        return _dt.strptime(raw, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _parse_month(raw: str | None):
    """'YYYY-MM' -> (year, month), o None."""
    from datetime import datetime as _dt
    if not raw:
        return None
    try:
        d = _dt.strptime(raw, "%Y-%m").date()
    except (ValueError, TypeError):
        return None
    return d.year, d.month


def _active_cohort_id(db):
    from itcj2.apps.titulatec.models import Cohort
    c = (db.query(Cohort).filter_by(status="open").order_by(Cohort.id.desc()).first()
         or db.query(Cohort).order_by(Cohort.id.desc()).first())
    return c.id if c else None


def _to_int(raw) -> int | None:
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _programs(db):
    from itcj2.core.models.program import Program
    return [{"id": p.id, "name": p.name} for p in db.query(Program).order_by(Program.name).all()]


def _people(db, procs):
    """Alumno y carrera de una lista de procesos, en 2 consultas (no N+1).

    Devuelve `(users, progs)` indexados por id; los llamadores hacen
    `users.get(proc.student_id)` y no vuelven a tocar la BD por fila.
    """
    from itcj2.core.models.user import User
    from itcj2.core.models.program import Program

    procs = [p for p in procs if p is not None]
    uids = {p.student_id for p in procs if p.student_id}
    pids = {p.program_id for p in procs if p.program_id}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(uids)).all()} if uids else {}
    progs = {g.id: g for g in db.query(Program).filter(Program.id.in_(pids)).all()} if pids else {}
    return users, progs


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


def _detail_ctx(db, process_id: int, *, user_id: int) -> dict | None:
    """Ficha del alumno seleccionado (zona C), acotada al alcance.

    Devuelve nombre, numero de control y correo del alumno, mas las `view_url` de
    sus 3 documentos iniciales: es la ficha completa. Resuelve el proceso por el
    predicado de alcance y no por `db.get`, como segunda linea de defensa — lo
    llaman `_shell_ctx` y, a traves de `_render_body`, las 5 acciones.
    """
    from itcj2.core.models.user import User
    from itcj2.core.models.program import Program
    from itcj2.apps.titulatec.models import Modality, Cohort, DocumentType
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.document_service import DocumentService
    from itcj2.apps.titulatec.services.scope_service import process_in_scope

    proc = process_in_scope(db, user_id, process_id)
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
    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
    allowed_days = [d.isoformat() for d in ReviewDayService.list_days(db, proc.cohort_id)] if proc.cohort_id else []
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
        "allowed_days": allowed_days,
        # Dia de SU cita: el detalle ofrece "ver ese dia" sin teclear la fecha.
        "day": appt.scheduled_at.date().isoformat() if appt and appt.scheduled_at else None,
    }


def _default_month(db, cohort_id, today):
    """Mes con el que abre el calendario: HOY, salvo que hoy sea un mes vacio.

    Si la convocatoria activa no tiene NINGUN dia de cotejo en el mes de hoy, se
    aterriza en el mes del proximo dia habilitado (o del ultimo, si ya pasaron
    todos). Es el mismo callejon sin salida que se le quito al boton "Del dia":
    abrir Citas en agosto y ver un mes vacio no dice donde esta el trabajo.
    """
    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService

    days = sorted(ReviewDayService.list_days(db, cohort_id)) if cohort_id else []
    if not days or any(d.year == today.year and d.month == today.month for d in days):
        return today.year, today.month
    futuros = [d for d in days if d >= today]
    ancla = futuros[0] if futuros else days[-1]
    return ancla.year, ancla.month


def _calendar_ctx(db, *, year, month, allowed, cohort_id, open_day):
    """Rejilla del mes + conteo de citas por dia, acotado por carrera."""
    import calendar as _cal
    from datetime import date as date_cls, datetime as _dt, time, timedelta
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService

    on_days = set(ReviewDayService.list_days(db, cohort_id)) if cohort_id else set()
    start = _dt.combine(date_cls(year, month, 1), time.min)
    end = (_dt.combine(date_cls(year, month, 28), time.min)
           + timedelta(days=7)).replace(day=1, hour=0, minute=0)
    counts = AppointmentService.counts_by_day(db, start, end, allowed_program_ids=allowed)

    weeks = []
    for wk in _cal.Calendar(firstweekday=0).monthdatescalendar(year, month):
        weeks.append([{"date": d.isoformat(), "day": d.day, "in_month": d.month == month,
                       "on": d in on_days, "count": counts.get(d, 0),
                       "is_open": open_day is not None and d == open_day}
                      for d in wk])

    prev_m = date_cls(year, month, 1) - timedelta(days=1)
    next_first = (date_cls(year, month, 28) + timedelta(days=7)).replace(day=1)
    return {
        "weeks": weeks,
        "weekdays": _WEEKDAYS_ES,
        "month_label": f"{_MONTHS_ES_FULL[month]} {year}",
        "month_value": f"{year}-{month:02d}",
        "prev_month": f"{prev_m.year}-{prev_m.month:02d}",
        "next_month": f"{next_first.year}-{next_first.month:02d}",
        "no_config": not on_days,
    }


def _time_label(dt) -> str:
    return f"{dt:%H:%M}" if dt else "—"


def _appt_rows(db, appts):
    """Filas de agenda (zona A, dia o lista) a partir de citas YA acotadas."""
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    users, progs = _people(db, [a.process for a in appts])
    rows = []
    for a in appts:
        proc = a.process
        u = users.get(proc.student_id) if proc else None
        prog = progs.get(proc.program_id) if proc and proc.program_id else None
        rows.append({
            "process_id": a.process_id,
            "folio": proc.folio if proc else "—",
            "student": u.full_name if u else "—",
            "control": u.control_number if u else "—",
            "program": prog.name if prog else "—",
            "time_label": _time_label(a.scheduled_at),
            "scheduled_label": _label(a.scheduled_at),
            "day": a.scheduled_at.date().isoformat() if a.scheduled_at else None,
            "status": a.status,
            "change_request": AppointmentService.has_change_request(a),
        })
    return rows


def _shell_ctx(db, *, user_id, view="", month="", date_raw="", selected_id=None,
               program_id=None, status=None, mine=False) -> dict:
    """Contexto de las TRES zonas de `#appt-shell`. Una sola resolucion de alcance."""
    from datetime import date as date_cls
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.scope_service import officer_programs

    scope = officer_programs(db, user_id)
    allowed = None if scope == "ALL" else scope
    cohort_id = _active_cohort_id(db)
    today = date_cls.today()

    # --- zona A: que se muestra en la columna de la agenda -------------------
    day = _parse_date(date_raw)
    if day is not None:
        zone = "day"
    elif view == "list":
        zone = "list"
    else:
        zone = "calendar"

    day_rows, list_rows, cal = [], [], None
    if zone == "day":
        day_rows = _appt_rows(db, AppointmentService.list_for_day(
            db, day, allowed_program_ids=allowed))
    elif zone == "list":
        list_rows = _appt_rows(db, AppointmentService.list_appointments(
            db, program_id=program_id, status=status or None,
            owner_id=user_id if mine else None, allowed_program_ids=allowed))

    # El calendario se calcula tambien en la vista de dia: la cabecera del dia
    # ofrece volver al mes que lo contiene y saber que dias estan habilitados.
    if zone in ("calendar", "day"):
        ym = _parse_month(month) or ((day.year, day.month) if day
                                     else _default_month(db, cohort_id, today))
        cal = _calendar_ctx(db, year=ym[0], month=ym[1], allowed=allowed,
                            cohort_id=cohort_id, open_day=day)

    # --- zona B: "Por agendar" (SIEMPRE, con contador) -----------------------
    # A proposito NO se le pasa `program_id`: es la cola de trabajo del encargado
    # y su contador tiene que ser estable. Los filtros de la zona A filtran la
    # zona A y nada mas.
    pending_procs = AppointmentService.list_pending_processes(
        db, allowed_program_ids=allowed)
    users, progs = _people(db, pending_procs)
    pending = []
    for p in pending_procs:
        u = users.get(p.student_id)
        prog = progs.get(p.program_id) if p.program_id else None
        pending.append({
            "process_id": p.id, "folio": p.folio,
            "student": u.full_name if u else "—",
            "control": u.control_number if u else "—",
            "program": prog.name if prog else "Sin carrera",
        })

    # --- zona C: detalle -----------------------------------------------------
    # El `?selected=` del querystring es un FILTRO, no una AMPLIACION del alcance.
    # `visible_ids` se calcula sobre el UNIVERSO ACOTADO COMPLETO (toda la agenda
    # del usuario + toda su cola), NO sobre las filas de la zona A: si se
    # estrechara al dia, `?date=X&selected=Y` dejaria de abrir a un alumno cuya
    # cita cae en otro dia — o a uno de "Por agendar", que no tiene cita.
    # La guarda dura sigue siendo `process_in_scope` dentro de `_detail_ctx`.
    visible_ids = (AppointmentService.agenda_process_ids(db, allowed_program_ids=allowed)
                   | {p.id for p in pending_procs})
    if selected_id is not None and selected_id not in visible_ids:
        selected_id = None
    detail = _detail_ctx(db, selected_id, user_id=user_id) if selected_id else None
    if detail is None:
        selected_id = None

    # --- querystrings para los enlaces --------------------------------------
    # `q_zone` = estado de la zona A, para enlaces que solo cambian de alumno.
    # `q_sel`  = alumno abierto, para enlaces que solo cambian la zona A.
    zone_params = []
    if zone == "day":
        zone_params.append(("date", day.isoformat()))
        if month:
            zone_params.append(("month", month))
    elif zone == "list":
        zone_params.append(("view", "list"))
        if program_id:
            zone_params.append(("program_id", str(program_id)))
        if status:
            zone_params.append(("status", status))
        if mine:
            zone_params.append(("mine", "1"))
    elif cal:
        zone_params.append(("month", cal["month_value"]))

    return {
        "zone": zone,
        "day": day.isoformat() if day else "",
        "day_label": _day_label(day),
        "day_rows": day_rows,
        "rows": list_rows,
        "cal": cal,
        "pending": pending,
        "pending_count": len(pending),
        "detail": detail,
        "selected_id": selected_id,
        "programs": _programs(db),
        "f_program": program_id or "", "f_status": status or "", "f_mine": mine,
        "page_url": PAGE_URL,
        "body_url": BODY_URL,
        "q_zone": urlencode(zone_params),
        "q_sel": urlencode([("selected", str(selected_id))]) if selected_id else "",
    }


def _render_body(request, db, *, selected_id, user_id, **kw):
    ctx = _shell_ctx(db, user_id=user_id, selected_id=selected_id, **kw)
    return render_titulatec(request, "titulatec/partials/appointments_body.html", ctx)


# ===========================================================================
# Páginas / parciales
# ===========================================================================
# Los parametros llegan como `str` (no `int | None`) a proposito: un filtro vacio
# viaja como `program_id=` y con un tipo entero FastAPI devolveria 422.

@router.get("", name="titulatec.pages.appointments.home")
async def home(
    request: Request,
    view: str = "",
    month: str = "",
    date: str = "",
    program_id: str = "",
    status: str = "",
    mine: int = 0,
    selected: str = "",
    user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS)),
):
    """Pagina completa. Acepta los MISMOS parametros que `/body` para que el
    `hx-push-url` sea un deep link de verdad: F5 reconstruye el estado."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _shell_ctx(db, user_id=int(user["sub"]), view=view, month=month,
                         date_raw=date, selected_id=_to_int(selected),
                         program_id=_to_int(program_id), status=status or None,
                         mine=bool(mine))
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/appointments.html", ctx)


@router.get("/body", name="titulatec.pages.appointments.body")
async def body(
    request: Request,
    view: str = "",
    month: str = "",
    date: str = "",
    program_id: str = "",
    status: str = "",
    mine: int = 0,
    selected: str = "",
    user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS)),
):
    """`#appt-shell` completo (agenda + por agendar + detalle) para el swap HTMX."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        return _render_body(request, db, selected_id=_to_int(selected),
                            user_id=int(user["sub"]), view=view, month=month,
                            date_raw=date, program_id=_to_int(program_id),
                            status=status or None, mine=bool(mine))
    finally:
        db.close()


# ===========================================================================
# Acciones (re-renderizan el shell, conservando alumno y zona A)
# ===========================================================================

def _action_ctx(request):
    """Estado de la zona A que los forms/botones de accion mandan en su
    querystring, para que tras agendar o marcar asistencia la agenda NO salte."""
    q = request.query_params
    return {"view": q.get("view", ""), "month": q.get("month", ""),
            "date_raw": q.get("date", ""), "program_id": _to_int(q.get("program_id")),
            "status": q.get("status") or None, "mine": bool(_to_int(q.get("mine")) or 0)}


@router.post("/{process_id}/schedule", name="titulatec.pages.appointments.schedule")
async def schedule(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.api.create"])),
):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    form = dict(await request.form())
    date_raw = form.get("appt_date")
    time_raw = form.get("appt_time")
    dt = _parse_dt(f"{date_raw}T{time_raw}") if date_raw and time_raw else None
    db = SessionLocal()
    try:
        from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
        proc = assert_process_in_scope(db, int(user["sub"]), process_id)
        if dt and not ReviewDayService.is_allowed(db, proc.cohort_id, dt.date()):
            return Response(status_code=400, headers={"X-Tt-Error": "Esa fecha no está habilitada para cotejo."})
        if dt:
            AppointmentService.create(
                db, process_id, scheduled_at=dt, location=(form.get("location") or None),
                created_by_id=int(user["sub"]), note=(form.get("note") or None))
        return _render_body(request, db, selected_id=process_id,
                            user_id=int(user["sub"]), **_action_ctx(request))
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
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    form = dict(await request.form())
    date_raw = form.get("appt_date")
    time_raw = form.get("appt_time")
    dt = _parse_dt(f"{date_raw}T{time_raw}") if date_raw and time_raw else None
    db = SessionLocal()
    try:
        from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
        proc = assert_process_in_scope(db, int(user["sub"]), process_id)
        if dt and not ReviewDayService.is_allowed(db, proc.cohort_id, dt.date()):
            return Response(status_code=400, headers={"X-Tt-Error": "Esa fecha no está habilitada para cotejo."})
        appt = AppointmentService.get_for_process(db, process_id)
        if appt and dt:
            AppointmentService.reschedule(
                db, appt, scheduled_at=dt, location=(form.get("location") or None),
                actor_id=int(user["sub"]), note=(form.get("note") or None))
        return _render_body(request, db, selected_id=process_id,
                            user_id=int(user["sub"]), **_action_ctx(request))
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
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    db = SessionLocal()
    try:
        assert_process_in_scope(db, int(user["sub"]), process_id)
        appt = AppointmentService.get_for_process(db, process_id)
        if appt:
            AppointmentService.start(db, appt, int(user["sub"]))
        return _render_body(request, db, selected_id=process_id,
                            user_id=int(user["sub"]), **_action_ctx(request))
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
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    db = SessionLocal()
    try:
        assert_process_in_scope(db, int(user["sub"]), process_id)
        appt = AppointmentService.get_for_process(db, process_id)
        if appt:
            AppointmentService.mark_attended(db, appt, int(user["sub"]))
        return _render_body(request, db, selected_id=process_id,
                            user_id=int(user["sub"]), **_action_ctx(request))
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
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    db = SessionLocal()
    try:
        assert_process_in_scope(db, int(user["sub"]), process_id)
        appt = AppointmentService.get_for_process(db, process_id)
        if appt:
            AppointmentService.mark_no_show(db, appt, int(user["sub"]))
        return _render_body(request, db, selected_id=process_id,
                            user_id=int(user["sub"]), **_action_ctx(request))
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
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope
    from itcj2.apps.titulatec.utils import storage

    db = SessionLocal()
    try:
        # Antes de tocar disco: aqui viaja el acta de nacimiento / la CURP.
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
    return FileResponse(str(path), media_type=mime,
                        headers={"Content-Disposition": f'inline; filename="{original}"'})
