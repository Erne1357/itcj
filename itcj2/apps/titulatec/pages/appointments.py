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

from fastapi import APIRouter, Depends, Form, HTTPException, Request
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
    """La convocatoria que manda en la agenda: la `open` más nueva y, si no hay,
    la `closed` más nueva. NUNCA una `draft`.

    El respaldo era `order_by(id.desc()).first()` sin mirar el status. Daba igual
    mientras toda convocatoria naciera `open`; ahora que se crean en `draft` y se
    abren desde el editor de ventana, ese respaldo aterrizaba justo en la que
    todavía no existe para nadie — la agenda del encargado se quedaba en blanco
    con la convocatoria de verdad a un id de distancia.
    """
    from itcj2.apps.titulatec.models import Cohort
    c = (db.query(Cohort).filter_by(status="open").order_by(Cohort.id.desc()).first()
         or db.query(Cohort).filter_by(status="closed").order_by(Cohort.id.desc()).first())
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
        "change_request": appt.change_request,
    }


def _detail_ctx(db, process_id: int, *, user_id: int, doc_abierto=None) -> dict | None:
    """Ficha del alumno seleccionado (zona C), acotada al alcance.

    Devuelve nombre, numero de control y correo del alumno, mas las `view_url` de
    sus 3 documentos iniciales: es la ficha completa. Resuelve el proceso por el
    predicado de alcance y no por `db.get`, como segunda linea de defensa — lo
    llaman `_shell_ctx` y, a traves de `_render_body`, las acciones.

    Desde el 2026-09-07 trae tambien el CHECKLIST de requisitos de cotejo
    (`requisitos`, `can_mark_reqs`), con las mismas claves que el expediente: el
    oficial dictamina la fase 2 aqui mismo y sin eso «Aprobar» contestaria
    «faltan: e.firma» sin ofrecer donde palomearlo.
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

    from itcj2.apps.titulatec.utils import storage

    docs = []
    for code in _INITIAL_DOC_TYPES:
        dt = db.query(DocumentType).filter_by(code=code).first()
        doc = DocumentService.get_document(db, process_id, code)
        # `missing` se resuelve EN EL SERVIDOR. Sin esto, un archivo que ya no
        # esta en disco dejaba una caja gris de 460-520 px sin una sola palabra:
        # el visor no tenia estado de error.
        falta = True
        if doc:
            try:
                falta = not storage.abs_path(doc.file_path).exists()
            except Exception:          # ruta imposible de resolver: se trata igual
                falta = True
        docs.append({
            "type_code": code,
            "name": dt.name if dt else code,
            "doc": ({"original_name": doc.original_name, "review_status": doc.review_status,
                     "size_bytes": doc.size_bytes or 0} if doc else None),
            "missing": bool(doc) and falta,
            "view_url": f"/titulatec/admin/appointments/{process_id}/document/{code}",
        })

    # El documento abierto es ESTADO DE SERVIDOR, no del DOM. Idiomorph conserva
    # el nodo del <iframe> pero SINCRONIZA SUS ATRIBUTOS, y `src` es uno: sin
    # esto, marcar asistencia recargaba el PDF desde cero.
    legibles = [d for d in docs if d["doc"] and not d["missing"]]
    abierto = next((d for d in legibles if d["type_code"] == doc_abierto),
                   legibles[0] if legibles else None)

    # ---- requisitos de cotejo de la fase 2 (§5.4) ----
    #
    # Replica LITERAL de `pages/admin.py::_detail_ctx`, y por las mismas dos
    # razones:
    #
    # * Lectura NO SEMBRADORA. `RequirementService.list_with_status` enruta a
    #   `CotejoRequirementService.list_or_seed` -> `seed_defaults(commit=True)`:
    #   un simple GET del panel COMMITEARIA ocho filas en la convocatoria del
    #   alumno. Se copia la forma de consulta de `missing_required`, que ya es
    #   la no sembradora, y la siembra se queda donde pertenece.
    # * Diccionarios PLANOS, no objetos ORM. La ruta renderiza DESPUES de su
    #   `db.close()` y un atributo expirado sobre una instancia desanclada
    #   lanzaria `DetachedInstanceError`. En los tests NO se ve: el `close()`
    #   del harness es un no-op deliberado, asi que el invariante se afirma
    #   sobre la FORMA del contexto (`test_appt_fase2.py`).
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
    # contesta 403 es peor que no estar. Con `user_id=None` el checklist sale
    # apagado, no roto.
    can_mark_reqs = False
    if user_id is not None:
        from itcj2.core.services.authz_service import get_user_permissions_for_app
        can_mark_reqs = ("titulatec.process.api.requirement.mark"
                         in get_user_permissions_for_app(db, user_id, "titulatec"))

    appt = AppointmentService.get_for_process(db, process_id)

    # Historial de INTENTOS (spec 2026-09-15 §2.2). Es el unico sitio de la app
    # donde el encargado puede ver que esta es la tercera vez que se le agenda a
    # alguien: `get_for_process` devuelve solo la vigente, asi que sin esto los
    # intentos superados, cancelados y las ausencias viejas son invisibles.
    # Diccionarios PLANOS, por la misma razon que `requisitos` arriba: la ruta
    # renderiza DESPUES de su `db.close()`.
    intentos = [{
        "n": a.attempt_no,
        "when": _label(a.scheduled_at),
        "status": a.status,
        "by_student": a.booked_by == "student",
        "is_current": bool(a.is_current),
    } for a in AppointmentService.list_attempts(db, process_id)]

    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
    allowed_days = [d.isoformat() for d in ReviewDayService.list_days(db, proc.cohort_id)] if proc.cohort_id else []

    # Estatus de la solicitud de liberación de GTV para la encuesta de
    # egresados (D3). Dict plano de `summary_for_process`: esta ruta renderiza
    # DESPUÉS de su `db.close()`, igual que `requisitos` arriba.
    from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService
    survey = SurveyReviewService.summary_for_process(db, process_id)

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
        "attempts": intentos,
        "docs": docs,
        "doc_abierto": abierto["type_code"] if abierto else None,
        "doc_src": abierto["view_url"] if abierto else None,
        "allowed_days": allowed_days,
        # Dia de SU cita: el detalle ofrece "ver ese dia" sin teclear la fecha.
        "day": appt.scheduled_at.date().isoformat() if appt and appt.scheduled_at else None,
        # MISMAS claves que el expediente: la fila del checklist es un contrato
        # compartido entre las dos plantillas.
        "requisitos": requisitos,
        "can_mark_reqs": can_mark_reqs,
        "survey": survey,
    }


def _dow_es(d) -> str:
    """'jue'. `calendar.day_abbr` sale en el locale del proceso, que en el
    contenedor es C y devolvia 'Thu' en una UI en espanol."""
    return ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"][d.weekday()]


def _dia_largo(d) -> str:
    """'jueves 07 de septiembre' — para el pager y los mensajes."""
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    return f"{dias[d.weekday()]} {d.day:02d} de {_MONTHS_ES_FULL[d.month].lower()}"


def _default_day(db, cohort_id, allowed, today):
    """El dia CON TRABAJO, que es donde tiene que abrir la pestana.

    Generaliza a `_default_month`. El orden importa: hoy si es dia de cotejo;
    si no, el proximo dia de cotejo que tenga citas; si no, el proximo dia de
    cotejo a secas; y si todos pasaron, el ultimo. Abrir en un dia vacio no
    dice donde esta el trabajo, que es el callejon sin salida que ya se le
    quito al boton «Del dia».
    """
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService

    dias = sorted(ReviewDayService.list_days(db, cohort_id)) if cohort_id else []
    if not dias:
        return None
    if today in dias:
        return today
    futuros = [d for d in dias if d >= today]
    for d in futuros:
        if AppointmentService.list_for_day(db, d, allowed_program_ids=allowed):
            return d
    return futuros[0] if futuros else dias[-1]


def _time_label(dt) -> str:
    return f"{dt:%H:%M}" if dt else "—"


def _appt_rows(db, appts):
    """Filas de agenda a partir de citas YA acotadas."""
    rows = []
    users, progs = _people(db, [a.process for a in appts])
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
            "change_request": bool(a.change_request),
        })
    return rows


def _dias_ctx(db, cohort_id, *, abierto, today):
    """El carril de dias: uno por dia real de la convocatoria, con su ocupacion.

    Sustituye al calendario mensual, del que 29 de sus 35 celdas eran inertes:
    el trabajo son seis mananas concretas.

    La ocupacion sale de UNA sola funcion (`SlotService.day_occupancy`), la
    misma que alimenta la cabecera del tablero: con dos numeradores distintos
    la pantalla mostraba dos cifras que no cuadraban. Y NO se acota por
    carrera: la carrera decide que NOMBRES se ven, nunca los conteos.
    """
    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
    from itcj2.apps.titulatec.services.slot_service import SlotService

    salida = []
    for fila in (ReviewDayService.list_rows(db, cohort_id) if cohort_id else []):
        ventanas = SlotService.windows_for_day(db, fila.id)
        ocupados, capacidad = SlotService.day_occupancy(db, ventanas)
        salida.append({
            "date": fila.date.isoformat(),
            "day": fila.date.day,
            "dow": _dow_es(fila.date),
            "mes": _MONTHS_ES[fila.date.month],
            "largo": _dia_largo(fila.date),
            "ocupados": ocupados,
            "capacidad": capacidad,
            "sin_espacio": capacidad == 0,
            "lleno": capacidad > 0 and ocupados >= capacidad,
            "is_today": fila.date == today,
            "is_active": abierto is not None and fila.date == abierto,
        })
    return salida


def _board_ctx(db, day, allowed, *, user_id, cohort_id):
    """El tablero de un dia: una fila por franja, con quien la ocupa.

    Con capacidad 1 (lo normal) cada franja es una fila simple; con capacidad
    mayor la fila crece a N asientos de la MISMA caja, para que llenar un lugar
    no mueva nada de sitio.
    """
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
    from itcj2.apps.titulatec.services.slot_service import SlotService

    fila_dia = ReviewDayService.get(db, cohort_id, day) if (cohort_id and day) else None
    if fila_dia is None:
        return {"grupos": [], "sueltas": [], "ajenas": [], "sin_espacio": True}

    mias = SlotService.windows_for_day(db, fila_dia.id, owner_id=user_id)
    ajenas = [w for w in SlotService.windows_for_day(db, fila_dia.id)
              if w.owner_user_id != user_id]

    visibles = AppointmentService.list_for_day(db, day, allowed_program_ids=allowed)
    por_hueco = {}
    for a in visibles:
        por_hueco.setdefault((a.window_id, a.scheduled_at.time()), []).append(a)
    users, progs = _people(db, [a.process for a in visibles])
    vistos = {a.process_id for a in visibles}

    def _ficha(a):
        proc = a.process
        u = users.get(proc.student_id) if proc else None
        prog = progs.get(proc.program_id) if proc and proc.program_id else None
        return {
            "process_id": a.process_id,
            "student": u.full_name if u else "—",
            "control": u.control_number if u else "—",
            "program": prog.name if prog else "—",
            "status": a.status,
            "time_label": _time_label(a.scheduled_at),
            "change_request": bool(a.change_request),
            # D11: el encargado se entera del auto-agendado por su tablero, con
            # distintivo. No hay notificacion ni correo, asi que este dato ES
            # el aviso.
            "booked_by": a.booked_by,
        }

    grupos = []
    for w in mias:
        cupo = int(w.capacity or 1)
        franjas = []
        for hora in SlotService.slots(w):
            dentro = por_hueco.get((w.id, hora), [])
            franjas.append({
                "hhmm": hora.strftime("%H:%M"),
                "ocupantes": [_ficha(a) for a in dentro],
                "libres": max(0, cupo - len(dentro)),
                "cupo": cupo,
            })
        ocupados, capacidad = SlotService.window_occupancy(db, w)
        grupos.append({
            "id": w.id,
            "horario": f"{w.start_time:%H:%M}–{w.end_time:%H:%M}",
            "slot_minutes": w.slot_minutes,
            "capacity": cupo,
            "location": w.location,
            "pausada": w.status == "paused",
            "ocupados": ocupados,
            "capacidad": capacidad,
            "franjas": franjas,
            # Citas que dejaron de caer en la rejilla al cambiar la duracion.
            # Se muestran, no se esconden: el modelo lo permite y taparlo seria
            # peor que ensenarlo.
            "fuera": [_ficha(a) for a in SlotService.out_of_grid(db, w)
                      if a.process_id in vistos],
        })

    return {
        "grupos": grupos,
        # Citas heredadas sin ventana: la migracion caso las que pudo por horario.
        "sueltas": [_ficha(a) for a in visibles if a.window_id is None],
        # Solo conteos y horario. NUNCA nombres: pueden ser de carreras fuera
        # del alcance de este usuario.
        "ajenas": [{"horario": f"{w.start_time:%H:%M}–{w.end_time:%H:%M}",
                    "ocupados": SlotService.window_occupancy(db, w)[0],
                    "capacidad": SlotService.window_occupancy(db, w)[1]}
                   for w in ajenas],
        "sin_espacio": not mias,
    }


def _espacios_ctx(db, day, *, user_id, cohort_id, editando=None):
    """Mis espacios de un dia, mas el editor si hay uno abierto."""
    from itcj2.apps.titulatec.models import ReviewWindow
    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
    from itcj2.apps.titulatec.services.slot_service import SlotService

    from itcj2.apps.titulatec.services.scope_service import _program_ids_for_user

    fila_dia = ReviewDayService.get(db, cohort_id, day) if (cohort_id and day) else None
    if fila_dia is None:
        return {"dia_id": None, "mios": [], "ajenos": [], "editor": None,
                "defaults": None, "sin_alcance": False}

    # Ruling 14 de la ejecucion: `SelfBookingService.offer` resuelve la carrera
    # con ESTE mismo predicado, asi que quien no tenga carreras asignadas puede
    # publicar un espacio `bookable` que NINGUN egresado vera. Se mantiene
    # fail-closed (`read.all` es un permiso de lectura, no una declaracion de
    # que esa persona atiende presencialmente a todo el instituto), pero la UI
    # tiene que decirlo con todas sus letras: sin esto es un bug silencioso.
    sin_alcance = not _program_ids_for_user(db, user_id)

    mios = []
    for w in SlotService.windows_for_day(db, fila_dia.id, owner_id=user_id,
                                         solo_abiertas=False):
        ocupados, capacidad = SlotService.window_occupancy(db, w)
        mios.append({
            "id": w.id,
            "horario": f"{w.start_time:%H:%M}–{w.end_time:%H:%M}",
            "start": w.start_time.strftime("%H:%M"),
            "end": w.end_time.strftime("%H:%M"),
            "slot_minutes": w.slot_minutes,
            "capacity": w.capacity,
            "location": w.location,
            "pausada": w.status == "paused",
            "visibility": w.visibility,
            "ocupados": ocupados,
            "capacidad": capacidad,
            "is_active": editando is not None and editando == w.id,
        })

    ajenos = []
    for w in SlotService.windows_for_day(db, fila_dia.id, solo_abiertas=False):
        if w.owner_user_id == user_id:
            continue
        ocupados, capacidad = SlotService.window_occupancy(db, w)
        ajenos.append({"horario": f"{w.start_time:%H:%M}–{w.end_time:%H:%M}",
                       "ocupados": ocupados, "capacidad": capacidad})

    defaults = SlotService.day_defaults(db, fila_dia)
    editor = None
    editor_w = None
    if editando == "nuevo":
        editor = {"id": None,
                  "start": defaults["start_time"].strftime("%H:%M"),
                  "end": defaults["end_time"].strftime("%H:%M"),
                  "slot_minutes": defaults["slot_minutes"],
                  "capacity": defaults["capacity"],
                  "location": defaults["location"] or "",
                  # D1: todo espacio nace PRIVADO. Publicar es deliberado.
                  "visibility": "private",
                  "pausada": False}
    elif editando:
        w = db.get(ReviewWindow, editando)
        if w is not None and w.review_day_id == fila_dia.id:
            editor_w = w
            editor = {"id": w.id, "start": w.start_time.strftime("%H:%M"),
                      "end": w.end_time.strftime("%H:%M"),
                      "slot_minutes": w.slot_minutes, "capacity": w.capacity,
                      "location": w.location or "", "pausada": w.status == "paused",
                      "visibility": w.visibility,
                      "propio": w.owner_user_id == user_id}
    if editor is not None:
        n = len(SlotService.slots_from(editor["start"], editor["end"],
                                       editor["slot_minutes"]))
        editor["derivada"] = (
            f"De {editor['start']} a {editor['end']} en franjas de "
            f"{editor['slot_minutes']} minutos: {n} franja{'s' if n != 1 else ''} "
            f"de {editor['capacity']} persona{'s' if editor['capacity'] != 1 else ''} "
            f"— {n * int(editor['capacity'])} citas en total.")

        # Las tres lineas de §6, calculadas EN EL SERVIDOR igual que la de
        # arriba. Dicen la verdad sobre ESTE espacio («tus 10 franjas libres»),
        # no una frase generica: duplicar el calculo de franjas en JavaScript es
        # justo lo que el editor evita desde su rediseno.
        # FRANJAS libres, no CITAS libres: `free_slots` devuelve `list[time]`
        # (una entrada por franja con lugar), asi que la rama del espacio nuevo
        # tiene que contar `n` a secas. Con `n * capacity` la frase decia «20
        # franjas libres» para 10 franjas de 2 personas — con cupo 1 coinciden,
        # que es justo lo que hacia pasar al test sin que el numero fuera cierto.
        libres = (len(SlotService.free_slots(db, editor_w)) if editor_w is not None
                  else n)
        lugar = editor["location"] or "el lugar que pongas arriba"
        editor["vis_lineas"] = {
            "private": "Solo tú agendas en este espacio. El egresado no lo ve.",
            "bookable": (f"El egresado ve tus {libres} "
                         f"franja{'s' if libres != 1 else ''} libre"
                         f"{'s' if libres != 1 else ''} y elige una."),
            "walkin": (f"El egresado ve «{_dia_largo(day)}, {editor['start']} a "
                       f"{editor['end']}, {lugar}» y llega sin cita."),
        }
    return {"dia_id": fila_dia.id, "mios": mios, "ajenos": ajenos,
            "editor": editor, "defaults": defaults, "sin_alcance": sin_alcance}


def _shell_ctx(db, *, user_id, v="", date_raw="", selected_id=None, q="",
               estado="", mias=False, program_id=None, mover=None, w=None,
               seleccion=None, doc="", rechazar=None, **_legacy) -> dict:
    """Contexto de `#appt-shell`: la zona fija mas la sub-vista que toque.

    Tres sub-vistas hermanas, no tres zonas peleandose por el ancho:

        agenda    donde esta el trabajo: carril de dias, tablero y cola
        atender   un alumno a la vez, a ancho completo
        espacios  el horario propio del encargado dentro de los dias de la jefa

    Cada una declara su rejilla UNA vez por breakpoint. Lo que cambia al abrir
    un alumno es QUE sub-vista se renderiza, nunca cuanto mide una columna: por
    eso ya no hay nada que se encoja ni que salte.

    Una sola resolucion de alcance para todas las consultas.
    """
    from datetime import date as date_cls
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.scope_service import officer_programs

    scope = officer_programs(db, user_id)
    allowed = None if scope == "ALL" else scope
    cohort_id = _active_cohort_id(db)
    today = date_cls.today()

    # `view=list` es la URL vieja: se traduce, no se rompe.
    if _legacy.get("view") == "list" and not v:
        v = "agenda"
        q = q or ""
        estado = estado or _legacy.get("status") or ""

    vista = v if v in ("agenda", "atender", "espacios", "reparto") else "agenda"

    # --- el dia abierto ------------------------------------------------------
    day = _parse_date(date_raw)
    day_resuelto = False
    if day is None:
        day = _default_day(db, cohort_id, allowed, today)
        day_resuelto = day is not None

    # --- zona C: el alumno abierto ------------------------------------------
    # El `?selected=` es un FILTRO, nunca una AMPLIACION del alcance: crudo fue
    # un IDOR. Se valida contra el universo acotado COMPLETO (toda la agenda del
    # usuario mas toda su cola), no contra las filas de la vista, o abrir a
    # alguien de otro dia dejaria de funcionar.
    pendientes = AppointmentService.list_pending_processes(db, allowed_program_ids=allowed)
    reagendar = AppointmentService.list_reschedule_processes(db, allowed_program_ids=allowed)
    # D2: documentos aprobados pero SIN la encuesta enviada. No se puede
    # agendar a nadie de este cubo (la guarda de `AppointmentService.create`
    # lo rechazaría), así que sus filas no llevan navegación ni arrastre — ver
    # `_appt_queue.html`. No entran a `visibles`: no hay ficha que abrirles.
    sin_encuesta = AppointmentService.list_missing_survey_processes(db, allowed_program_ids=allowed)
    # D10: los que agotaron su tope de cancelaciones (D9) y ya NO pueden
    # agendarse solos. Cubo propio y mutuamente excluyente con «Por agendar»:
    # la resta la hace `list_pending_processes`, no esta vista.
    bloqueados = AppointmentService.list_self_blocked_processes(db, allowed_program_ids=allowed)
    # D5: se les atendio y la fase 02 quedo RECHAZADA, asi que necesitan otra
    # cita. Cubo propio porque conservan su cita vigente (`attended`), lo que los
    # deja fuera del universo «sin cita» del que salen los cubos 1, 2 y 4, y no
    # son `no_show`, asi que «Reagendar» tampoco los veia: sin este cubo no
    # estaban en NINGUNO. No hace falta sumarlos a `visibles`: su cita vigente ya
    # los mete por `agenda_process_ids`, asi que el `?selected=` les abre ficha.
    rechazados = AppointmentService.list_rejected_cotejo_processes(
        db, allowed_program_ids=allowed)
    # Los bloqueados ENTRAN a `visibles`, y no es un detalle: `?selected=` se
    # descarta si el proceso no esta aqui, asi que sin esta union el encargado
    # veria el cubo pero no podria abrirle la ficha a nadie de el — o sea, no
    # podria agendarle, que es lo unico que ese cubo existe para pedirle.
    visibles = (AppointmentService.agenda_process_ids(db, allowed_program_ids=allowed)
                | {p.id for p in pendientes} | {p.id for p in bloqueados})
    if selected_id is not None and selected_id not in visibles:
        selected_id = None
    detail = (_detail_ctx(db, selected_id, user_id=user_id, doc_abierto=doc)
              if selected_id else None)
    if detail is None:
        selected_id = None
    # «Atender» SIN alumno ya no cae de vuelta a Agenda: es la sala de espera
    # del dia. Antes era un destino falso, solo alcanzable eligiendo a alguien
    # primero, asi que la pestana existia pero no se podia pulsar.

    # --- el modo del area de trabajo ----------------------------------------
    buscando = bool((q or "").strip() or estado or mias or program_id)
    modo = "resultados" if buscando else "dia"

    ctx = {
        "v": vista, "modo": modo,
        "day": day.isoformat() if day else "",
        "day_largo": _dia_largo(day) if day else "",
        "day_resuelto": day_resuelto,
        "dias": _dias_ctx(db, cohort_id, abierto=day, today=today),
        "detail": detail, "selected_id": selected_id,
        "mover": mover,
        # Modo «estoy escribiendo el motivo del rechazo de la fase 02». Viaja
        # por querystring como `mover`, no por un `prompt()` (prohibido) ni por
        # `hx-confirm` (que es si/no y no recoge texto).
        "rechazar": rechazar,
        "q": q or "", "f_estado": estado or "", "f_mias": mias,
        "f_program": program_id or "",
        "programs": _programs(db),
        "pending": _proc_rows(db, pendientes),
        "pending_count": len(pendientes),
        "bloqueados": _proc_rows_bloqueados(db, bloqueados),
        "bloqueados_count": len(bloqueados),
        "reagendar": _proc_rows(db, reagendar),
        "reagendar_count": len(reagendar),
        "rechazados": _proc_rows(db, rechazados),
        "rechazados_count": len(rechazados),
        # No se suma al badge de la pestaña (`appointments_body.html`): ese
        # contador es "por atender" (agendar + reagendar) y este cubo no se
        # puede atender todavía — solo informa.
        "sin_encuesta": _proc_rows(db, sin_encuesta),
        "sin_encuesta_count": len(sin_encuesta),
        "seleccion": sorted(seleccion or []),
        "page_url": PAGE_URL, "body_url": BODY_URL,
    }

    if vista == "agenda":
        if modo == "resultados":
            ctx["rows"] = _appt_rows(db, AppointmentService.list_appointments(
                db, program_id=program_id, status=estado or None,
                owner_id=user_id if mias else None,
                allowed_program_ids=allowed, q=q))
        else:
            ctx["board"] = _board_ctx(db, day, allowed, user_id=user_id,
                                      cohort_id=cohort_id)
    elif vista == "atender":
        ctx["pager"] = _pager_ctx(db, day, allowed, selected_id)
        # Sin alumno tambien: la sala de espera es la lista del dia.
    elif vista == "espacios":
        ctx["espacios"] = _espacios_ctx(db, day, user_id=user_id,
                                        cohort_id=cohort_id, editando=w)

    ctx["q_zone"] = urlencode(_zone_params(ctx))
    ctx["q_sel"] = urlencode([("selected", str(selected_id))]) if selected_id else ""
    return ctx


def _zone_params(ctx):
    """Estado de la sub-vista, para que las acciones no hagan saltar la agenda."""
    p = [("v", ctx["v"])]
    if ctx["day"]:
        p.append(("date", ctx["day"]))
    if ctx.get("q"):
        p.append(("q", ctx["q"]))
    if ctx.get("f_estado"):
        p.append(("estado", ctx["f_estado"]))
    if ctx.get("f_mias"):
        p.append(("mias", "1"))
    if ctx.get("f_program"):
        p.append(("program_id", str(ctx["f_program"])))
    if ctx.get("detail"):
        p.append(("doc", ctx["detail"].get("doc_abierto") or ""))
    return [(k, v) for k, v in p if v != ""]


def _proc_rows(db, procs):
    """Filas de la cola: alumno, control y carrera de procesos SIN cita util."""
    users, progs = _people(db, procs)
    salida = []
    for p in procs:
        u = users.get(p.student_id)
        prog = progs.get(p.program_id) if p.program_id else None
        salida.append({"process_id": p.id, "folio": p.folio,
                       "student": u.full_name if u else "—",
                       "control": u.control_number if u else "—",
                       "program": prog.name if prog else "Sin carrera"})
    return salida


def _proc_rows_bloqueados(db, procs):
    """Filas del cubo de D10, con el conteo que EXPLICA por que estan ahi.

    «3 cancelaciones · ya no puede agendar solo» es lo que convierte una lista
    mas en una instruccion: sin el numero, el encargado no sabe si mirar el
    cubo es urgente o si el alumno simplemente no ha entrado a la pagina.

    El conteo sale de `SelfBookingService.cancellations`, el MISMO predicado
    que decide el cubo y que ve el alumno en su pantalla. Es un COUNT por fila,
    y se acepta a proposito: este cubo solo tiene a quien cancelo tres veces,
    asi que N es de un digito.
    """
    from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService
    por_id = {p.id: p for p in procs}
    filas = _proc_rows(db, procs)
    for fila in filas:
        fila["cancelaciones"] = SelfBookingService.cancellations(
            db, por_id[fila["process_id"]])
    return filas


def _pager_ctx(db, day, allowed, selected_id):
    """«‹ Anterior · 3 de 12 · jueves 07 de septiembre · Siguiente ›».

    Permite recorrer el dia sin volver a la agenda entre alumno y alumno, que
    eran ~30 idas y vueltas por manana. La tira lleva NOMBRE Y APELLIDO, no
    iniciales: cuando alguien llega fuera de orden hay que encontrarlo de un
    vistazo.
    """
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    if not day:
        return None
    filas = _appt_rows(db, AppointmentService.list_for_day(
        db, _parse_date(day) if isinstance(day, str) else day,
        allowed_program_ids=allowed))
    if not filas:
        return None
    ids = [f["process_id"] for f in filas]
    i = ids.index(selected_id) if selected_id in ids else None
    return {
        "filas": filas,
        "total": len(filas),
        "pos": (i + 1) if i is not None else None,
        "anterior": ids[i - 1] if i not in (None, 0) else None,
        "siguiente": ids[i + 1] if i is not None and i + 1 < len(ids) else None,
        "fin": i is not None and i + 1 == len(ids),
    }


def _hdr(msg: str) -> str:
    """Codifica un mensaje para que quepa en un header HTTP.

    Los valores de header son latin-1 por especificacion, y Starlette los
    codifica asi. Un mensaje con acentos —o sea, todos los nuestros— llega al
    cliente como bytes que no son UTF-8 validos y revienta al decodificarlos.

    Nunca habia saltado porque la unica rama que ponia `X-Tt-Error` con acentos
    era la de fecha no habilitada, que ningun test alcanzaba.

    Se percent-codifica aqui y `titulatec-utils.js` lo decodifica al mostrarlo.
    """
    from urllib.parse import quote
    return quote(str(msg), safe="")


def _window_y_franja(db, form, proc, user_id):
    """(window_id, franja) a partir de lo que mande el formulario.

    Acepta las DOS formas mientras dure la transicion:

      * la nueva, que es la que de verdad respeta el cupo: `window_id` y
        `slot_start` (HH:MM) salen de picar una franja del tablero;
      * la vieja, `appt_date` + `appt_time`, que se resuelve contra las
        ventanas del dia con `SlotService.resolve`. Sirve para que las citas
        heredadas y cualquier enlace viejo sigan funcionando.

    Devuelve `(None, None)` si no hay datos: el service lo traduce a
    `MissingSchedule`, que es 400 con mensaje. Antes esto era un `if dt:` que
    respondia 200 sin escribir nada y sin decir una palabra.
    """
    from itcj2.apps.titulatec.services.slot_service import SlotService

    wid = _to_int(form.get("window_id"))
    slot = _parse_time(form.get("slot_start"))
    if wid and slot:
        return wid, slot

    dia = _parse_date(form.get("appt_date"))
    hhmm = _parse_time(form.get("appt_time"))
    if not dia or not hhmm or not proc.cohort_id:
        return None, None
    window, franja = SlotService.resolve(db, proc.cohort_id, dia, hhmm,
                                         owner_id=user_id)
    return (window.id if window else None), franja


def _parse_time(raw):
    """'09:30' -> time(9,30), o None. Un valor basura NO revienta la pagina."""
    from datetime import datetime as _dt
    if not raw:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return _dt.strptime(str(raw), fmt).time()
        except (ValueError, TypeError):
            continue
    return None


def _accion(request, db, *, selected_id, user_id, fn, exito=None):
    """Ejecuta una accion de la agenda y traduce sus errores de dominio.

    Dos familias, y la diferencia importa:

    * **Entrada del usuario** (falta la franja, el dia no esta habilitado, la
      hora no cae en la rejilla) -> 400 + `X-Tt-Error`. htmx NO swappea en 4xx,
      y esta bien: lo que hay en pantalla sigue siendo verdad.
    * **Colision de estado** (otro encargado gano la franja, la cita ya cambio)
      -> **200 con el cuerpo re-renderizado**, que ya trae la realidad nueva,
      mas el mensaje en `X-Tt-Notice`. Con un 4xx el encargado se quedaria
      mirando un tablero rancio que sigue pintando libre el asiento que otro
      acaba de ocupar: el error se ve, pero la pantalla miente.
    """
    from itcj2.apps.titulatec.services.appointment_errors import (
        AppointmentError, SlotLockTimeout,
    )
    try:
        fn()
    except AppointmentError as e:
        # Casi todos estos errores se levantan ANTES de escribir nada, asi que
        # no hay nada que deshacer. El unico que envenena la transaccion es el
        # timeout del lock, porque nace de un error de Postgres.
        #
        # Y el rollback no es gratis: bajo el `join_transaction_mode` del harness
        # de tests descarta tambien las filas que sembraron las factories, asi
        # que hacerlo "por si acaso" rompe pruebas que no tienen nada que ver.
        if isinstance(e, SlotLockTimeout):
            db.rollback()
        if not e.refresca_la_vista:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(e)})
        resp = _render_body(request, db, selected_id=selected_id,
                            user_id=user_id, **_action_ctx(request))
        resp.headers["X-Tt-Notice"] = _hdr(e)
        return resp
    resp = _render_body(request, db, selected_id=selected_id,
                        user_id=user_id, **_action_ctx(request))
    # Una accion que sale bien tambien tiene que decirlo: el encargado acaba de
    # tocar algo con consecuencias para un egresado y la pantalla se repinta
    # entera. Sin esto, agendar y no agendar se ven casi igual.
    if exito:
        resp.headers["X-Tt-Notice"] = _hdr(exito)
        resp.headers["X-Tt-Notice-Kind"] = "success"
    return resp


def _render_body(request, db, *, selected_id, user_id, **kw):
    ctx = _shell_ctx(db, user_id=user_id, selected_id=selected_id, **kw)
    return render_titulatec(request, "titulatec/partials/appointments_body.html", ctx)


# ===========================================================================
# Páginas / parciales
# ===========================================================================
# Los parametros llegan como `str` (no `int | None`) a proposito: un filtro vacio
# viaja como `program_id=` y con un tipo entero FastAPI devolveria 422.

def _params(request):
    """Los parametros de la vista, tal cual llegan.

    Se leen SIEMPRE del querystring y no de la firma de cada ruta: son ocho y
    viajan iguales en las paginas, en `/body` y en cada accion. Todos como
    `str`: un filtro vacio llega como `program_id=` y con un tipo entero FastAPI
    devolveria 422.
    """
    q = request.query_params
    return {
        "v": q.get("v", ""),
        "date_raw": q.get("date", ""),
        "selected_id": _to_int(q.get("selected")),
        "q": q.get("q", ""),
        "estado": q.get("estado", ""),
        "mias": bool(_to_int(q.get("mias")) or 0),
        "program_id": _to_int(q.get("program_id")),
        "mover": _to_int(q.get("mover")),
        "rechazar": _to_int(q.get("rechazar")),
        "w": (q.get("w") if q.get("w") == "nuevo" else _to_int(q.get("w"))),
        "seleccion": {int(x) for x in q.getlist("p") if str(x).isdigit()},
        "doc": q.get("doc", ""),
        # URLs viejas que se traducen en vez de romperse.
        "view": q.get("view", ""),
        "status": q.get("status", ""),
    }


@router.get("", name="titulatec.pages.appointments.home")
async def home(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS)),
):
    """Pagina completa. Acepta los MISMOS parametros que `/body`, para que el
    `hx-push-url` sea un deep link de verdad: F5 reconstruye el estado."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _shell_ctx(db, user_id=int(user["sub"]), **_params(request))
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/appointments.html", ctx)


@router.get("/body", name="titulatec.pages.appointments.body")
async def body(
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=_VIEW_PERMS)),
):
    """`#appt-shell` completo para el swap HTMX."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        return _render_body(request, db, user_id=int(user["sub"]), **_params(request))
    finally:
        db.close()


# ===========================================================================
# Acciones (re-renderizan el shell, conservando la sub-vista y el dia)
# ===========================================================================

def _action_ctx(request):
    """Estado de la vista que las acciones mandan en su propio querystring, para
    que tras agendar o marcar asistencia la pantalla NO salte de sitio.

    `mover`, `rechazar` y la seleccion se DESCARTAN a proposito: son estados de
    «estoy a mitad de una accion», y la accion ya termino. Si sobrevivieran, el
    tablero seguiria ofreciendo «Mover aqui» despues de haber movido, y el panel
    seguiria pidiendo el motivo despues de haber rechazado.
    """
    p = _params(request)
    p.pop("selected_id", None)
    p["mover"] = None
    p["rechazar"] = None
    p["seleccion"] = set()
    return p


@router.post("/{process_id}/schedule", name="titulatec.pages.appointments.schedule")
async def schedule(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.api.create"])),
):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    from itcj2.apps.titulatec.services.slot_service import SlotService

    form = dict(await request.form())
    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, uid, process_id)
        window_id, slot = _window_y_franja(db, form, proc, uid)
        return _accion(request, db, selected_id=process_id, user_id=uid,
                       fn=lambda: AppointmentService.create(
                           db, process_id, window_id=window_id, slot_start=slot,
                           created_by_id=uid,
                           location=(form.get("location") or None)))
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
    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, uid, process_id)
        appt = AppointmentService.get_for_process(db, process_id)
        if appt is None:
            return Response(status_code=400,
                            headers={"X-Tt-Error": _hdr("Ese alumno todavía no tiene cita.")})
        window_id, slot = _window_y_franja(db, form, proc, uid)
        return _accion(request, db, selected_id=process_id, user_id=uid,
                       fn=lambda: AppointmentService.reschedule(
                           db, appt, window_id=window_id, slot_start=slot,
                           actor_id=uid, location=(form.get("location") or None)))
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
        uid = int(user["sub"])
        assert_process_in_scope(db, uid, process_id)
        appt = AppointmentService.get_for_process(db, process_id)
        if appt is None:
            return Response(status_code=400,
                            headers={"X-Tt-Error": _hdr("Ese alumno todavía no tiene cita.")})
        return _accion(request, db, selected_id=process_id, user_id=uid,
                       fn=lambda: AppointmentService.start(db, appt, uid),
                       exito="Cotejo iniciado.")
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
        uid = int(user["sub"])
        assert_process_in_scope(db, uid, process_id)
        appt = AppointmentService.get_for_process(db, process_id)
        if appt is None:
            return Response(status_code=400,
                            headers={"X-Tt-Error": _hdr("Ese alumno todavía no tiene cita.")})
        return _accion(request, db, selected_id=process_id, user_id=uid,
                       fn=lambda: AppointmentService.mark_attended(db, appt, uid),
                       exito="Cotejo concluido. Aprueba la fase 02 en el proceso.")
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
        uid = int(user["sub"])
        assert_process_in_scope(db, uid, process_id)
        appt = AppointmentService.get_for_process(db, process_id)
        if appt is None:
            return Response(status_code=400,
                            headers={"X-Tt-Error": _hdr("Ese alumno todavía no tiene cita.")})
        return _accion(request, db, selected_id=process_id, user_id=uid,
                       fn=lambda: AppointmentService.mark_no_show(db, appt, uid),
                       exito="Quedó registrado que no se presentó. Su lugar no se libera.")
    finally:
        db.close()


@router.post("/{process_id}/cancelar", name="titulatec.pages.appointments.cancel")
def cancel(
    process_id: int,
    request: Request,
    motivo: str = Form(""),
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.api.update"])),
):
    """El encargado cancela la cita de un alumno (spec 2026-09-15 §5).

    D12: cancelar LIBERA la franja en el acto, al reves que el no-show. Son dos
    botones distintos a proposito y no dos nombres de lo mismo: «no se presento»
    registra una ausencia y conserva el lugar consumido; «cancelar» dice que la
    cita no va a ocurrir y devuelve el lugar al pozo.

    **No consume el cupo de D9.** El contador del alumno solo cuenta las que
    cancelo EL (`cancelled_by_id == student_id`, `SelfBookingService.cancellations`),
    asi que el encargado no puede dejarlo bloqueado sin querer.

    El `motivo` es opcional y viaja por `Form`: la ruta es `def` —como sus
    hermanas `move` y `space_save`— y en una `def` no se puede
    `await request.form()`. Se normaliza ANTES de abrir la sesion, para que el
    guard de alcance siga siendo la primera sentencia del `try` (lo vigila el
    censo por AST de `test_scope_guard.py`).
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    uid = int(user["sub"])
    razon = (motivo or "").strip() or None
    db = SessionLocal()
    try:
        assert_process_in_scope(db, uid, process_id)
        appt = AppointmentService.get_for_process(db, process_id)
        if appt is None:
            return Response(status_code=400,
                            headers={"X-Tt-Error": _hdr("Ese alumno todavía no tiene cita.")})
        return _accion(request, db, selected_id=process_id, user_id=uid,
                       fn=lambda: AppointmentService.cancel(db, appt, uid, razon),
                       exito="Cita cancelada. El lugar queda libre para otro egresado.")
    finally:
        db.close()


# ===========================================================================
# Dictamen de la fase 02, aqui mismo (§5.4-5.5, D9)
# ===========================================================================
# Tres rutas HERMANAS de las del expediente, no las mismas. Las de `admin.py`
# (`process_requirement`, `phase_approve`, `phase_reject`) terminan en
# `_render_detail_body`, que renderiza `partials/processes/_exp_shell.html`
# apuntando a `hx-target="#exp-shell"`: cableadas desde Citas, el swap meteria
# el expediente ENTERO dentro de `#appt-shell`. Estas devuelven `_render_body`,
# que es el shell de Citas, igual que `attended` y `no_show`.
#
# El checklist va al lado de los botones a proposito: la Tarea 7 hizo que
# `approve_phase(proc, 2)` se niegue mientras falte un requisito obligatorio, asi
# que dos botones a secas contestarian «faltan: e.firma» y mandarian al oficial
# al expediente a palomearlo — el viaje que esta pantalla elimina.
#
# Un solo codigo de permiso por ruta: `require_page_app(perms=[...])` es un OR, y
# un segundo codigo regalaria la feature a quien lo tenga.

@router.post("/{process_id}/requisitos/{rid}",
             name="titulatec.pages.appointments.req_mark")
async def req_mark(
    process_id: int,
    rid: int,
    request: Request,
    user: dict = Depends(require_page_app(
        "titulatec", perms=["titulatec.process.api.requirement.mark"])),
):
    """El oficial marca, dispensa o desmarca un requisito de cotejo del alumno.

    Gemela de `pages/admin.py::process_requirement` salvo por el shell que
    devuelve. Repite sus dos guardas:

    * el requisito tiene que ser de la convocatoria del alumno (si no, un `rid`
      de otra convocatoria acreditaria algo que su lista ni pide);
    * los que llevan `auto_source` son de SOLO LECTURA: los acredita el sistema
      (hoy, la encuesta de egresados) y marcarlos a mano romperia la
      trazabilidad de `external_ref`.

    Contrato de `note`: AUSENTE conserva la que hubiera, PRESENTE Y VACIO la
    borra. `RequirementService.fulfill` lee `None` como «el llamador no lo
    manda», asi que normalizar el vacio a `None` dejaria al oficial sin forma de
    corregir una nota equivocada.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.models import CotejoRequirement
    from itcj2.apps.titulatec.services.requirement_service import RequirementService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    form = dict(await request.form())
    accion = (form.get("action") or "mark").strip()
    nota = form["note"].strip() if "note" in form else None

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, uid, process_id)

        req = (db.query(CotejoRequirement)
               .filter_by(id=rid, cohort_id=proc.cohort_id).first())
        if req is None:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(
                "Ese requisito no es de la convocatoria del alumno.")})
        if req.auto_source:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(
                "Ese requisito lo acredita el sistema; no se marca a mano.")})

        if accion == "unmark":
            RequirementService.unfulfill(db, process_id, rid, actor_id=uid)
        else:
            RequirementService.fulfill(
                db, process_id, rid, source="officer", checked_by_id=uid,
                note=nota,
                status=("waived" if accion == "waive" else "fulfilled"),
            )
        return _render_body(request, db, selected_id=process_id, user_id=uid,
                            **_action_ctx(request))
    finally:
        db.close()


@router.post("/{process_id}/fase2/aprobar",
             name="titulatec.pages.appointments.fase2_approve")
async def fase2_approve(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app(
        "titulatec", perms=["titulatec.process.api.approve_phase"])),
):
    """Libera la fase 02 sin salir del panel.

    La fase va FIJA (`PHASE_COTEJO`) y no por path: esta pantalla es la de la
    fase 2 y aceptar un `{n}` cualquiera convertiria la agenda de citas en un
    dictaminador universal de fases.

    El `ValueError` del service —fase que no toca, proceso cerrado, o el checklist
    incompleto de la Tarea 7, que NOMBRA lo que falta— sale como 400 +
    `X-Tt-Error`: htmx no swappea en 4xx, asi que el checklist sigue en pantalla
    con el alumno enfrente.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, uid, process_id)
        try:
            PhaseService.approve_phase(db, proc, PhaseService.PHASE_COTEJO, uid)
        except ValueError as exc:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        resp = _render_body(request, db, selected_id=process_id, user_id=uid,
                            **_action_ctx(request))
        resp.headers["X-Tt-Notice"] = _hdr("Fase 02 aprobada. El alumno avanza.")
        resp.headers["X-Tt-Notice-Kind"] = "success"
        return resp
    finally:
        db.close()


@router.post("/{process_id}/fase2/rechazar",
             name="titulatec.pages.appointments.fase2_reject")
async def fase2_reject(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app(
        "titulatec", perms=["titulatec.process.api.reject_phase"])),
):
    """Rechaza la fase 02 con motivo obligatorio.

    Sin motivo, al alumno le llega «Fase rechazada» a secas en su panel y tiene
    que venir a preguntar que falta; la exigencia es la misma que ya hacen la
    bandeja de Documentos y el expediente.

    Se valida ANTES de abrir sesion: un motivo vacio no debe costar ni una
    consulta. `reject_phase` NO consulta el checklist a proposito (Tarea 7):
    rechazar es justamente lo que se hace cuando falta algo.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    form = dict(await request.form())
    reason = (form.get("reason") or "").strip()
    if not reason:
        return Response(status_code=400, headers={"X-Tt-Error": _hdr(
            "Escribe el motivo del rechazo: es lo que el alumno lee.")})

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        proc = assert_process_in_scope(db, uid, process_id)
        try:
            PhaseService.reject_phase(db, proc, PhaseService.PHASE_COTEJO, uid, reason)
        except ValueError as exc:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        resp = _render_body(request, db, selected_id=process_id, user_id=uid,
                            **_action_ctx(request))
        resp.headers["X-Tt-Notice"] = _hdr("Fase 02 rechazada. Se le aviso al alumno.")
        return resp
    finally:
        db.close()


# ===========================================================================
# Ver documento subido por el alumno (para cotejo contra el físico)
# ===========================================================================

@router.post("/{process_id}/move", name="titulatec.pages.appointments.move")
def move(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.api.reschedule"])),
):
    """Mueve la cita a la franja que se acaba de picar en el tablero.

    Sustituye al formulario desplegable de reagendar, que empujaba lo que
    acababas de leer y ademas traia el campo de hora VACIO, asi que habia que
    volver a teclearla. Aqui no se teclea nada: se pica un lugar que existe.

    Es `def` y no `async def` a proposito: el ORM es sincrono y el `FOR UPDATE`
    de `SlotService` dentro de un `async def` bloquearia el event loop del
    worker entero. En `def`, FastAPI la corre en el threadpool.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.appointment_service import (
        AppointmentService, _ESTADOS_ACTIVOS,
    )
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    q = request.query_params
    uid = int(user["sub"])
    db = SessionLocal()
    try:
        assert_process_in_scope(db, uid, process_id)
        appt = AppointmentService.get_for_process(db, process_id)
        window_id = _to_int(q.get("window_id"))
        slot = _parse_time(q.get("slot"))
        cuando = slot.strftime("%H:%M") if slot else "esa hora"
        # `appt is None` NO basta como proxy de «no hay cita que mover».
        # `get_for_process` devuelve la VIGENTE, y una `attended` sigue siendo
        # la vigente: caia en `reschedule` -> `InvalidTransition`, asi que el
        # encargado no podia re-sentar desde el tablero a quien atendio y le
        # faltaron papeles — que es literalmente D5. El criterio correcto es el
        # complemento exacto de la guarda de `create` (`previa.status in
        # _ESTADOS_ACTIVOS`): hay cita VIVA que mover, o se abre un intento
        # nuevo. Asi los dos no pueden divergir. `cancelled`/`superseded` ni
        # llegan aqui: dejan de ser vigentes, asi que `appt` ya es None.
        if appt is None or appt.status not in _ESTADOS_ACTIVOS:
            return _accion(request, db, selected_id=process_id, user_id=uid,
                           fn=lambda: AppointmentService.create(
                               db, process_id, window_id=window_id, slot_start=slot,
                               created_by_id=uid),
                           exito=f"Cita agendada a las {cuando}. Se avisó al alumno.")
        return _accion(request, db, selected_id=process_id, user_id=uid,
                       fn=lambda: AppointmentService.reschedule(
                           db, appt, window_id=window_id, slot_start=slot, actor_id=uid),
                       exito=f"Cita movida a las {cuando}. Se avisó al alumno.")
    finally:
        db.close()


@router.post("/{process_id}/undo-no-show", name="titulatec.pages.appointments.undo_no_show")
def undo_no_show(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.api.update"])),
):
    """«Deshacer no se presento».

    Marcar una ausencia le dispara notificacion a un egresado y hasta ahora no
    tenia reverso: un clic de mas en una manana de prisa costaba una llamada.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        assert_process_in_scope(db, uid, process_id)
        appt = AppointmentService.get_for_process(db, process_id)
        if appt is None:
            return Response(status_code=400,
                            headers={"X-Tt-Error": _hdr("Ese alumno todavía no tiene cita.")})
        return _accion(request, db, selected_id=process_id, user_id=uid,
                       fn=lambda: AppointmentService.undo_no_show(db, appt, uid),
                       exito="Listo, la cita vuelve a estar en proceso.")
    finally:
        db.close()


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


# ===========================================================================
# Espacios de cotejo (sub-vista «Espacios»)
# ===========================================================================
# La jefatura pone los DIAS; cada encargado abre en ellos sus ventanas.
#
# Son `def` y no `async def` a proposito: el ORM es sincrono y el `FOR UPDATE`
# de `SlotService` dentro de un `async def` bloquearia el event loop del worker
# entero. En `def`, FastAPI las corre en el threadpool.

_ESPACIO_PERMS = ["titulatec.review_window.api.manage",
                  "titulatec.review_window.api.manage.all"]

# Los tres modos de un espacio (D1). Espejo del `CheckConstraint` del modelo:
# si alguna vez divergen, gana la BD y el usuario se lleva un 500.
_VISIBILIDADES = ("private", "bookable", "walkin")


def _puede_todo(db, user_id: int) -> bool:
    """Si el usuario puede editar los espacios de CUALQUIERA (jefatura)."""
    from itcj2.core.services.authz_service import get_user_permissions_for_app
    try:
        perms = get_user_permissions_for_app(db, user_id, "titulatec")
    except Exception:
        return False
    return "titulatec.review_window.api.manage.all" in perms


def _espacio_en_alcance(db, window_id, user_id: int):
    """La ventana, si este usuario puede tocarla. 404 si no.

    404 y no 403: el id es secuencial, y un 403 confirmaria que existe.
    """
    from itcj2.apps.titulatec.services.review_window_service import ReviewWindowService
    w = ReviewWindowService.get(db, window_id) if window_id else None
    if w is None or not ReviewWindowService.puede_editar(
            w, user_id, manage_all=_puede_todo(db, user_id)):
        raise HTTPException(status_code=404, detail="Espacio no encontrado")
    return w


def _accion_espacio(request, db, *, user_id, fn, exito=None, kind="success"):
    """Como `_accion`, pero para Espacios: no hay alumno seleccionado.

    `kind` decide el tono del aviso. No todo lo que sale bien sale BIEN del
    todo: publicar un espacio sin carreras asignadas se guarda, pero no lo vera
    nadie, y anunciarlo en verde seria mentir con el color.
    """
    from itcj2.apps.titulatec.services.appointment_errors import (
        AppointmentError, SlotLockTimeout,
    )
    try:
        fn()
        db.commit()
    except AppointmentError as e:
        if isinstance(e, SlotLockTimeout):
            db.rollback()
        if not e.refresca_la_vista:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(e)})
        resp = _render_body(request, db, selected_id=None, user_id=user_id,
                            **_action_ctx(request))
        resp.headers["X-Tt-Notice"] = _hdr(e)
        return resp
    # `selected_id` es OBLIGATORIO en `_render_body` y aqui no hay alumno
    # abierto, asi que va explicito en None. Sin el, TODA accion de Espacios que
    # salia bien (guardar, pausar, borrar, copiar) reventaba con un `TypeError`
    # -> 500: la sub-vista no tenia ni una sola prueba de ruta, solo de servicio,
    # asi que el fallo vivia justo en el hueco entre las dos capas.
    resp = _render_body(request, db, selected_id=None, user_id=user_id,
                        **_action_ctx(request))
    if exito:
        resp.headers["X-Tt-Notice"] = _hdr(exito)
        resp.headers["X-Tt-Notice-Kind"] = kind
    return resp


@router.post("/espacios/{window_id}", name="titulatec.pages.appointments.space_save")
def space_save(
    window_id: str,
    request: Request,
    start_time: str = Form(""),
    end_time: str = Form(""),
    slot_minutes: str = Form("30"),
    capacity: str = Form("1"),
    location: str = Form(""),
    visibility: str = Form("private"),
    user: dict = Depends(require_page_app("titulatec", perms=_ESPACIO_PERMS)),
):
    """Crea o actualiza un espacio. `window_id` es un entero o la palabra 'nuevo'.

    Los campos llegan por `Form(...)` y no leyendo el cuerpo a mano: la ruta es
    `def` (para no bloquear el event loop con el `FOR UPDATE`) y en una `def` no
    se puede `await request.form()`.

    `visibility` es un CAMPO MAS, sin ruta ni permiso propios (spec §5): quien
    puede editar un espacio puede publicarlo. Se valida aqui contra el dominio
    porque el `CheckConstraint` de la tabla lo rechazaria con un `IntegrityError`
    crudo, o sea un 500 en vez de una frase.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
    from itcj2.apps.titulatec.services.review_window_service import ReviewWindowService
    from itcj2.apps.titulatec.services.scope_service import _program_ids_for_user

    if visibility not in _VISIBILIDADES:
        return Response(status_code=400, headers={
            "X-Tt-Error": _hdr("Ese modo de visibilidad no existe.")})

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        campos = dict(
            start_time=start_time, end_time=end_time,
            slot_minutes=_to_int(slot_minutes) or 30,
            capacity=_to_int(capacity) or 1,
            location=(location or None),
            visibility=visibility,
        )
        # Ruling 14: `offer` es fail-closed, asi que un `bookable` de alguien sin
        # carreras asignadas no se lo ofrece a NADIE. Se guarda igual —el
        # predicado no cambia—, pero callarlo convierte un espacio publicado en
        # un bug silencioso: el encargado cree que publico y no publico nada.
        avisa_sin_alcance = (visibility == "bookable"
                             and not _program_ids_for_user(db, uid))
        exito = ("Espacio guardado, pero NINGÚN egresado lo verá: no tienes "
                 "carreras asignadas. Pídele a la jefatura de Servicios "
                 "Escolares que te asigne las que atiendes."
                 if avisa_sin_alcance else "Espacio guardado.")
        kind = "warning" if avisa_sin_alcance else "success"
        if window_id == "nuevo":
            dia = _parse_date(request.query_params.get("date"))
            cohort_id = _active_cohort_id(db)
            fila = ReviewDayService.get(db, cohort_id, dia) if (cohort_id and dia) else None
            if fila is None:
                return Response(status_code=400, headers={
                    "X-Tt-Error": _hdr("Ese día no está habilitado para cotejo.")})
            pos = _puesto_del_usuario(db, uid)
            return _accion_espacio(request, db, user_id=uid,
                                   fn=lambda: ReviewWindowService.create(
                                       db, fila.id, uid, position_id=pos,
                                       actor_id=uid, **campos),
                                   exito=exito, kind=kind)
        w = _espacio_en_alcance(db, _to_int(window_id), uid)
        return _accion_espacio(request, db, user_id=uid,
                               fn=lambda: ReviewWindowService.update(db, w, **campos),
                               exito=exito, kind=kind)
    finally:
        db.close()


@router.post("/espacios/{window_id}/pausa", name="titulatec.pages.appointments.space_pause")
def space_pause(
    window_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=_ESPACIO_PERMS)),
):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.review_window_service import ReviewWindowService

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        w = _espacio_en_alcance(db, window_id, uid)
        return _accion_espacio(request, db, user_id=uid,
                               fn=lambda: ReviewWindowService.toggle_pause(db, w),
                               exito="Listo, el espacio cambió de estado.")
    finally:
        db.close()


@router.post("/espacios/{window_id}/eliminar", name="titulatec.pages.appointments.space_delete")
def space_delete(
    window_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=_ESPACIO_PERMS)),
):
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.review_window_service import ReviewWindowService

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        w = _espacio_en_alcance(db, window_id, uid)
        return _accion_espacio(request, db, user_id=uid,
                               fn=lambda: ReviewWindowService.delete(db, w),
                               exito="Espacio eliminado.")
    finally:
        db.close()


@router.post("/espacios/{window_id}/copiar", name="titulatec.pages.appointments.space_copy")
def space_copy(
    window_id: int,
    request: Request,
    user: dict = Depends(require_page_app("titulatec", perms=_ESPACIO_PERMS)),
):
    """Replica el horario en los demás días de cotejo que aún no tengan uno."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
    from itcj2.apps.titulatec.services.review_window_service import ReviewWindowService

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        w = _espacio_en_alcance(db, window_id, uid)
        cohort_id = _active_cohort_id(db)
        ids = [f.id for f in ReviewDayService.list_rows(db, cohort_id)] if cohort_id else []
        return _accion_espacio(request, db, user_id=uid,
                               fn=lambda: ReviewWindowService.copy_to_days(db, w, ids),
                               exito="Horario copiado a los días que no tenían espacio.")
    finally:
        db.close()


def _puesto_del_usuario(db, user_id: int):
    """El puesto vigente que le da titulatec, para dejarlo desnormalizado.

    Sirve para alcance y auditoría; el dueño de la ventana sigue siendo el
    USUARIO, porque `aux_school_services` admite varios ocupantes.
    """
    from itcj2.core.models.position import UserPosition
    fila = (db.query(UserPosition)
            .filter(UserPosition.user_id == user_id)
            .order_by(UserPosition.id.desc()).first())
    return fila.position_id if fila else None
