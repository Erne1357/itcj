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
`counts_by_day`, `queue_candidates`) mas `agenda_process_ids`. Los defaults
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
        "scheduled_label": AppointmentService.when(appt)["label"],
        "scheduled_input": _input_value(appt.scheduled_at),
        "location": appt.location,
        "status": appt.status,
        "confirmed": appt.confirmed_at is not None,
        "change_request": appt.change_request,
    }


def _detail_ctx(db, process_id: int, *, user_id: int, doc_abierto=None) -> dict | None:
    """Ficha del alumno seleccionado (zona C), acotada al alcance.

    Devuelve nombre, numero de control y correo del alumno, mas las `view_url` de
    sus documentos iniciales (3 en licenciatura, 7 en posgrado -- Tarea 4, spec
    2026-09-30-titulatec-posgrado-design.md §4.4): es la ficha completa.
    Resuelve el proceso por el predicado de alcance y no por `db.get`, como
    segunda linea de defensa — lo llaman `_shell_ctx` y, a traves de
    `_render_body`, las acciones.

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
    from itcj2.apps.titulatec.services.track_service import TrackService

    proc = process_in_scope(db, user_id, process_id)
    if not proc:
        return None
    student = db.get(User, proc.student_id)
    program = db.get(Program, proc.program_id) if proc.program_id else None
    modality = db.get(Modality, proc.modality_id) if proc.modality_id else None
    cohort = db.get(Cohort, proc.cohort_id)

    from itcj2.apps.titulatec.utils import storage

    # Perfil del proceso (spec 2026-09-30-titulatec-posgrado-design.md §4.4,
    # Tarea 4): licenciatura/"sin carrera" listan los 3 de siempre; posgrado,
    # los 7. `program` ya está cargado arriba, así que `for_level` reusa ese
    # mismo objeto en vez de que `TrackService.for_process` repita el
    # `db.get(Program, ...)` (aunque saldría del identity map, esto evita
    # incluso esa segunda vuelta).
    track = TrackService.for_level(program.level if program else None)
    codes = DocumentService.initial_doc_types(track)

    # R-G (spec 2026-09-30-titulatec-posgrado-design.md §5, invariante 8;
    # Ruling R11, revisión final): dos pasadas -- la primera trae `dt`/`doc`
    # por código (igual que antes), la segunda ya sabe el `present_codes`
    # completo para preguntarle a `excused_initial_docs` (predicado PURO,
    # sin `db`) qué extras se DISPENSAN. `initial_docs_phase` solo se
    # consulta para POSGRADO -- licenciatura nunca tiene codigos en
    # `POSGRADO_EXTRA_DOCS`, asi que la pregunta ni se plantea.
    from itcj2.apps.titulatec.services.track_service import TRACK_POSGRADO

    _filas = []
    for code in codes:
        dt = db.query(DocumentType).filter_by(code=code).first()
        doc = DocumentService.get_document(db, process_id, code)
        _filas.append((code, dt, doc))

    initial_docs_phase = None
    if track == TRACK_POSGRADO:
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        initial_docs_phase = PhaseService.phase_number_for_code(db, "initial_docs")
    excused = DocumentService.excused_initial_docs(
        proc, frozenset(code for code, _dt, doc in _filas if doc is not None),
        initial_docs_phase=initial_docs_phase)

    docs = []
    for code, dt, doc in _filas:
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
            "excused": doc is None and code in excused,
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
    # Respaldo «Constancia previa…» / «Deshacer» (D9, spec 2026-10-01-
    # titulatec-biblioteca-caja-design.md §4.9): el permiso propio de SE
    # (`titulatec.library_clearance.api.prior`, ya otorgado por el DML) Y el
    # proceso no revocado -sobre una inscripción revocada no hay nada que
    # registrar y la ruta respondería 400-, igual que el expediente
    # (`pages/admin.py::_detail_ctx`; M2 de la revisión final: el panel lo
    # ofrecía junto a la «Revocada» de m42, al que llega una cita `attended`
    # que `ProcessService.cancel` deja vigente).
    can_register_prior = False
    if user_id is not None:
        from itcj2.core.services.authz_cache import cached_perms
        _user_perms = cached_perms(db, user_id, "titulatec")
        can_mark_reqs = "titulatec.process.api.requirement.mark" in _user_perms
        can_register_prior = ("titulatec.library_clearance.api.prior" in _user_perms
                              and proc.status != "cancelled")

    appt = AppointmentService.get_for_process(db, process_id)

    # Historial de INTENTOS (spec 2026-09-15 §2.2). Es el unico sitio de la app
    # donde el encargado puede ver que esta es la tercera vez que se le agenda a
    # alguien: `get_for_process` devuelve solo la vigente, asi que sin esto los
    # intentos superados, cancelados y las ausencias viejas son invisibles.
    # Diccionarios PLANOS, por la misma razon que `requisitos` arriba: la ruta
    # renderiza DESPUES de su `db.close()`.
    intentos = [{
        "n": a.attempt_no,
        "when": AppointmentService.when(a)["label"],
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

    # Mismo trato para el no adeudo de biblioteca (D9, Tarea 11): dict plano
    # de `LibraryClearanceService.summary_for_process`, MISMA fuente que el
    # expediente (`pages/admin.py::_detail_ctx`).
    from itcj2.apps.titulatec.services.library_clearance_service import (
        LibraryClearanceService,
    )
    library = LibraryClearanceService.summary_for_process(db, process_id)

    # Celda «Constancia» de las dos filas (Ruling R14, revisión final de
    # `2026-10-02-titulatec-constancias-y-pendientes-design.md` §3.4): UNA
    # llamada a `print_status_map` para encuesta y no adeudo juntos -a lo más
    # 2 consultas por vista, invariante 2- con los refs que EXISTAN (sin
    # solicitud o sin fila no se pide nada), colgada como `certificate` en
    # cada resumen (`None` si no aplica). Los `summary_for_process` no la
    # consultan: también los usan el tablero del egresado, «Mi cita» y las
    # páginas públicas. MISMO bloque que `pages/admin.py::_detail_ctx`.
    from itcj2.apps.titulatec.services.certificate_service import CertificateService

    ref_encuesta = SurveyReviewService.certificate_ref(survey["review_id"])
    ref_biblioteca = LibraryClearanceService.certificate_ref(library["clearance_id"])
    impresion = CertificateService.print_status_map(
        db, [ref for ref in (ref_encuesta, ref_biblioteca) if ref])
    survey["certificate"] = impresion.get(ref_encuesta)
    library["certificate"] = impresion.get(ref_biblioteca)

    # «Atender ahora» (D7, spec 2026-09-29-titulatec-cotejo-espacios-design.md
    # §4): los espacios SIN HORARIO de HOY de quien mira la ficha, abiertos y
    # con sus lugares libres, SOLO si el encargado le abriria un intento NUEVO.
    # D7 dice «sin cita viva», no «sin cita» (ruling de la revision de T6), y
    # sin cita viva son tres casos: sin cita vigente, vigente `no_show` (no
    # llego a su cita; hoy esta enfrente) y vigente `attended` con la fase 02
    # RECHAZADA (D5: le faltaron papeles y volvio). Una `attended` con la fase
    # por dictaminar o ya aprobada NO: el cotejo ya ocurrio y lo que sigue es
    # el dictamen, no otra cita. El dia es el de la convocatoria activa y tiene
    # que seguir habilitado: en uno cerrado `create` contestaria
    # `DayNotAllowed`, y un boton que siempre falla es peor que no estar.
    # `libres` = cupo total menos TODAS las vivas del espacio, de cualquier
    # hora (`SlotService.occupancy`, como en `_espacios_ctx`). Diccionarios
    # planos, por la misma razon que `requisitos` arriba.
    from itcj2.apps.titulatec.models import ProcessPhase
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.slot_service import SlotService
    from itcj2.core.utils.timezone import db_now

    abriria_intento = (
        appt is None or appt.status == "no_show"
        or (appt.status == "attended"
            and db.query(ProcessPhase.status)
                  .filter_by(process_id=process_id,
                             phase_number=PhaseService.PHASE_COTEJO)
                  .scalar() == "rejected"))

    # I-3 (revisión final): las dos formas de abrir un intento NUEVO —«Agendar
    # a este alumno» y «Atender ahora»— pasarían por la guarda dura de
    # `AppointmentService.create` y morirían con `SurveyNotSubmitted` /
    # `SurveyNotReleased` / `LibraryNotCleared` si al alumno le falta alguna
    # LIBERACIÓN. Sin esto la ficha ofrecía un botón que el servidor siempre
    # iba a rechazar. Quién decide es `ClearanceGate` (spec 2026-10-01-
    # titulatec-biblioteca-caja-design.md §4.4.5, invariante 2), con los
    # bloqueos ya partidos por liberación para que la ficha diga CUÁL falta.
    # Solo importa cuando de verdad se abriría un intento (`abriria_intento`):
    # con una `attended` pendiente de dictamen o ya aprobada el encargado no
    # va a agendar nada, así que los flags se quedan apagados y no contradicen
    # la píldora que YA pinta el checklist de requisitos (`detail.survey`).
    from itcj2.apps.titulatec.services.clearance_gate import (
        LIBRARY_BLOCKERS, SURVEY_BLOCKERS, ClearanceGate,
    )
    liberaciones = ClearanceGate.status(db, process_id)
    bloqueos = set(ClearanceGate.blockers(liberaciones)) if abriria_intento else set()
    encuesta_sin_liberar = bool(bloqueos & set(SURVEY_BLOCKERS))
    biblioteca_sin_liberar = bool(bloqueos & set(LIBRARY_BLOCKERS))

    hoy = db_now().date()
    walkins_hoy = []
    if user_id is not None and abriria_intento and not bloqueos:
        cohort_activa = _active_cohort_id(db)
        fila_hoy = ReviewDayService.get(db, cohort_activa, hoy) if cohort_activa else None
        if fila_hoy is not None and not fila_hoy.is_closed:
            for w in SlotService.windows_for_day(db, fila_hoy.id, owner_id=user_id):
                if w.visibility != "walkin":
                    continue
                vivas = sum(SlotService.occupancy(db, w).values())
                walkins_hoy.append({
                    "id": w.id,
                    "horario": f"{w.start_time:%H:%M}–{w.end_time:%H:%M}",
                    "libres": max(0, int(w.capacity or 1) - vivas),
                })

    return {
        "process": {"id": proc.id, "folio": proc.folio, "current_phase": proc.current_phase,
                    "status": proc.status},
        "student": {"name": student.full_name if student else "—",
                    "control": student.control_number if student else "—",
                    "email": student.email if student else None},
        "program_name": program.name if program else None,
        # Perfil ya resuelto arriba -- alimenta `track_pill` junto a la
        # carrera en `_appt_attend.html:69`.
        "track": track,
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
        "library": library,
        "can_register_prior": can_register_prior,
        "walkins_hoy": walkins_hoy,
        # I-3: `liberaciones_pendientes` apaga «Agendar a este alumno» /
        # «Atender ahora» en la plantilla cuando abrirían un intento que la
        # guarda dura rechazaría; `encuesta_sin_liberar` /
        # `biblioteca_sin_liberar` dicen cuál falta (una píldora y una frase
        # por cada una). `survey_status`/`library_status` son los de
        # `ClearanceGate.status`, para `survey_review_pill` /
        # `library_clearance_pill` (`_macros.html`).
        "liberaciones_pendientes": bool(bloqueos),
        "encuesta_sin_liberar": encuesta_sin_liberar,
        "biblioteca_sin_liberar": biblioteca_sin_liberar,
        "survey_status": liberaciones["survey"],
        "library_status": liberaciones["library"],
        # «Atender ahora» vuelve a la ficha en el dia de HOY, que es donde
        # queda la cita, no en el que se estaba mirando.
        "hoy": hoy.isoformat(),
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
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService

    rows = []
    users, progs = _people(db, [a.process for a in appts])
    for a in appts:
        proc = a.process
        u = users.get(proc.student_id) if proc else None
        prog = progs.get(proc.program_id) if proc and proc.program_id else None
        info = AppointmentService.when(a)
        rows.append({
            "process_id": a.process_id,
            "folio": proc.folio if proc else "—",
            "student": u.full_name if u else "—",
            "control": u.control_number if u else "—",
            "program": prog.name if prog else "—",
            # D11: en sin horario no hay una hora fija que enseñar.
            "time_label": "Sin horario" if info["sin_horario"] else _time_label(a.scheduled_at),
            "scheduled_label": info["label"],
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


# ===========================================================================
# Varios días a la vez (D9, spec §5) — «También en estos días» / «Copiar»
# ===========================================================================
# UNA sola fuente para «qué día es válido para crear/copiar un espacio»: de la
# convocatoria activa, ABIERTO (no cerrado) y `>= hoy`. La usan tanto las
# casillas que se ofrecen en el editor como la validación de lo que llega por
# POST — así una casilla nunca ofrece un día que la ruta luego vaya a ignorar
# en silencio.

def _dias_validas(db, cohort_id):
    """Filas de `CohortReviewDay` que `create_many`/`copy_to_days` aceptan."""
    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
    from itcj2.core.utils.timezone import db_now
    if not cohort_id:
        return []
    hoy = db_now().date()
    return [f for f in ReviewDayService.list_rows(db, cohort_id) if f.date >= hoy]


def _dias_opciones_ctx(db, cohort_id, *, excluir_iso=None):
    """Casillas de «También en estos días» / «Copiar a otros días»."""
    return [{
        "id": f.id, "iso": f.date.isoformat(), "dow": _dow_es(f.date),
        "dom": f.date.day, "mon": _MONTHS_ES[f.date.month], "checked": False,
    } for f in _dias_validas(db, cohort_id) if f.date.isoformat() != excluir_iso]


def _dias_ids_por_iso(db, cohort_id, isos):
    """ISOs marcados -> ids de día VALIDOS, sin duplicar y en el orden en que
    llegaron. Lo que ya no aplica (día cerrado o pasado entre el render y el
    POST) se descarta en silencio, no truena."""
    validos = {f.date.isoformat(): f.id for f in _dias_validas(db, cohort_id)}
    return [validos[iso] for iso in dict.fromkeys(isos) if iso in validos]


def _mensaje_dias_saltados(saltados) -> str | None:
    """'Se saltaron 2 porque se enciman con otro espacio tuyo: mar 07, jue 09.'
    o la versión singular. `None` si no hubo ninguno."""
    if not saltados:
        return None
    m = len(saltados)
    fechas = ", ".join(f"{_dow_es(d)} {d.day:02d}" for d in saltados)
    return (f"Se salt{'aron' if m != 1 else 'ó'} {m} porque se encima"
           f"{'n' if m != 1 else ''} con otro espacio tuyo: {fechas}.")


def _board_ctx(db, day, allowed, *, user_id, cohort_id):
    """El tablero de un dia: una fila por franja, con quien la ocupa.

    Con capacidad 1 (lo normal) cada franja es una fila simple; con capacidad
    mayor la fila crece a N asientos de la MISMA caja, para que llenar un lugar
    no mueva nada de sitio.

    Un espacio SIN HORARIO (D3, D6, spec 2026-09-29-titulatec-cotejo-espacios-
    design.md §4) es un grupo aparte (`modo="sin_horario"`, contra
    `modo="franjas"` de los demas): no tiene franjas, tiene una LISTA numerada
    por orden de apartado. Se arma de una consulta PROPIA -- `estado NOT IN
    (cancelled, superseded)` sobre TODA la ventana, nunca por `is_current` --
    y no de `visibles` (que SI filtra por `is_current`, via `list_for_day`):
    una cita de LEGADO sentada a mano a una hora dentro del walkin (10:30, p.
    ej.) puede perder la vigencia sin dejar de ocupar un lugar, y con
    `visibles` desaparecia de la lista sin dejar de contar en `ocupados` (nota
    de la revision de T2). Mismo criterio que `SlotService.occupancy`, para
    que la lista y el contador de libres nunca diverjan.
    """
    from itcj2.apps.titulatec.models import ReviewAppointment
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
    from itcj2.apps.titulatec.services.slot_service import SlotService, _ESTADOS_QUE_LIBERAN
    from itcj2.core.utils.timezone import db_now

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

    # Vivas de cada sin horario MIO, ordenadas por orden de apartado
    # (`scheduled_at`, `id`). Una sola consulta para todos: se reparten por
    # `window_id` abajo.
    walkin_ids = [w.id for w in mias if w.visibility == "walkin"]
    walkin_vivas = {}
    if walkin_ids:
        q = db.query(ReviewAppointment).filter(ReviewAppointment.window_id.in_(walkin_ids))
        if _ESTADOS_QUE_LIBERAN:
            q = q.filter(~ReviewAppointment.status.in_(_ESTADOS_QUE_LIBERAN))
        for a in q.order_by(ReviewAppointment.scheduled_at, ReviewAppointment.id).all():
            walkin_vivas.setdefault(a.window_id, []).append(a)

    todos = list(visibles) + [a for filas in walkin_vivas.values() for a in filas]
    users, progs = _people(db, [a.process for a in todos])
    vistos = {a.process_id for a in visibles}

    def _ficha(a, n=None):
        proc = a.process
        # M-1 (revisión final): `walkin_vivas` es una consulta PROPIA, sin
        # filtro de alcance (a diferencia de `visibles`, que ya viene acotada
        # por `allowed_program_ids`) -- a propósito, porque una cita de OTRA
        # carrera puede seguir sentada en el sin horario de este encargado
        # (p.ej. la sentó a mano quien sí tenía `read.all` antes de que le
        # recortaran las carreras). Sin este chequeo, esa fila enseñaría
        # nombre, control y carrera de un alumno fuera del alcance del
        # usuario que mira el tablero.
        en_alcance = allowed is None or (proc is not None and proc.program_id in allowed)
        u = users.get(proc.student_id) if (en_alcance and proc) else None
        prog = progs.get(proc.program_id) if (en_alcance and proc and proc.program_id) else None
        # Helper "cuándo" (spec 2026-09-29-titulatec-cotejo-espacios-design.md
        # §6): en sin horario no hay una hora fija que enseñar en la caja.
        sin_horario = AppointmentService.when(a)["sin_horario"]
        ficha = {
            "process_id": a.process_id,
            # M-2 (revisión final): un `no_show` que sigue vivo en la lista
            # (D10) y una cita nueva del MISMO proceso pueden convivir en el
            # mismo espacio sin horario -comparten `process_id`-, así que la
            # fila necesita un id por CITA, no por proceso, o saldrían dos
            # elementos con el mismo id en el DOM.
            "appt_id": a.id,
            "student": (u.full_name if u else "—") if en_alcance else "Alumno de otra carrera",
            "control": (u.control_number if u else "—") if en_alcance else None,
            "program": (prog.name if prog else "—") if en_alcance else None,
            "en_alcance": en_alcance,
            "status": a.status,
            "time_label": "Sin horario" if sin_horario else _time_label(a.scheduled_at),
            "change_request": bool(a.change_request),
            # D11: el encargado se entera del auto-agendado por su tablero, con
            # distintivo. No hay notificacion ni correo, asi que este dato ES
            # el aviso.
            "booked_by": a.booked_by,
        }
        if n is not None:
            # Orden de apartado (D8, §4): posicion 1-based en la lista, no el
            # `attempt_no` del proceso.
            ficha["n"] = n
        return ficha

    hoy = db_now().date()
    grupos = []
    for w in mias:
        ocupados, capacidad = SlotService.window_occupancy(db, w)

        if w.visibility == "walkin":
            vivas = walkin_vivas.get(w.id, [])
            grupos.append({
                "id": w.id,
                "modo": "sin_horario",
                "horario": f"{w.start_time:%H:%M}–{w.end_time:%H:%M}",
                "location": w.location,
                "pausada": w.status == "paused",
                "capacidad": capacidad,
                "ocupados": ocupados,
                # `capacidad - ocupados`, nunca `len(lista)`: son la misma
                # poblacion por construccion, pero `window_occupancy` es la
                # UNICA fuente de verdad del cupo (la cabecera la usa igual).
                "libres": max(0, capacidad - ocupados),
                "apertura": w.start_time.strftime("%H:%M"),
                "es_hoy": day == hoy,
                "lista": [_ficha(a, n=i) for i, a in enumerate(vivas, start=1)],
            })
            continue

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
        grupos.append({
            "id": w.id,
            "modo": "franjas",
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
    from itcj2.apps.titulatec.services.review_window_service import (
        ReviewWindowService, WALKIN_CUPO_DEFAULT)
    from itcj2.apps.titulatec.services.slot_service import SlotService

    from itcj2.apps.titulatec.services.scope_service import _program_ids_for_user

    fila_dia = ReviewDayService.get(db, cohort_id, day) if (cohort_id and day) else None
    if fila_dia is None:
        return {"dia_id": None, "mios": [], "ajenos": [], "editor": None,
                "defaults": None, "sin_alcance": False, "dias_opciones": []}

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
                  # D12: el cupo TOTAL de un espacio nuevo nace en el default
                  # PLANO (decision del usuario 2026-09-29: "no creo que se
                  # puedan atender 500"), ya NO franjas del dia x cupo del
                  # dia -- ese calculo se retiro junto con el tope de 500.
                  "capacity_total": WALKIN_CUPO_DEFAULT,
                  "location": defaults["location"] or "",
                  # D1: todo espacio nace PRIVADO. Publicar es deliberado.
                  "visibility": "private",
                  "pausada": False}
    elif editando:
        w = db.get(ReviewWindow, editando)
        # PROPIEDAD, no solo el dia. Sin esta mitad,
        # `?v=espacios&date=...&w=<id ajeno>` renderizaba el editor de OTRO
        # encargado: horario, cupo, lugar y hasta la VISIBILIDAD, con los radios
        # premarcados — bastante mas de lo que la lista «de otros encargados»
        # ensena a proposito (solo horario y conteos, sin nombre, ver `ajenos`
        # arriba y `_appt_spaces.html`). Guardar ya daba 404
        # (`_espacio_en_alcance`), asi que el unico efecto neto era la fuga: htmx
        # no swappea en 4xx, y el encargado se llevaba un toast generico DESPUES
        # de haber leido datos que no le tocaban.
        #
        # Es el MISMO predicado de los caminos de escritura
        # (`ReviewWindowService.puede_editar`, que ya contempla el `manage.all`
        # de la jefatura), no una copia: con dos criterios, lo que se pinta y lo
        # que se deja guardar acabarian discrepando.
        #
        # Sin editor la vista cae a la lista de espacios del dia, que es
        # exactamente lo que ve quien no pasa ningun `w`. NO se levanta 404
        # aqui: esto es el render de la pagina entera, y tumbarla por un
        # parametro de mas seria peor que ignorarlo.
        if (w is not None and w.review_day_id == fila_dia.id
                and ReviewWindowService.puede_editar(
                    w, user_id, manage_all=_puede_todo(db, user_id))):
            editor_w = w
            # `capacity` efectiva (D3, spec §3.2): en `walkin` la columna YA es
            # el cupo TOTAL (T3), no el de por franja. El campo oculto que
            # necesita un valor VALIDO de todos modos —HTML5 sigue validando
            # lo que se oculta por CSS— cae al default del dia; al reves
            # cuando NO es walkin, `capacity_total` se deriva mas abajo, ya
            # con `n` conocido.
            if w.visibility == "walkin":
                cap_franja, cap_total = defaults["capacity"], w.capacity
            else:
                cap_franja, cap_total = w.capacity, None
            editor = {"id": w.id, "start": w.start_time.strftime("%H:%M"),
                      "end": w.end_time.strftime("%H:%M"),
                      "slot_minutes": w.slot_minutes, "capacity": cap_franja,
                      "capacity_total": cap_total,
                      "location": w.location or "", "pausada": w.status == "paused",
                      "visibility": w.visibility}
    if editor is not None:
        n = len(SlotService.slots_from(editor["start"], editor["end"],
                                       editor["slot_minutes"]))
        cap_franja = int(editor["capacity"])
        if editor["capacity_total"] is None:
            # D12: mismo default PLANO que un espacio nuevo (ya no franjas x
            # cupo) para el campo oculto de "Personas en total" de un espacio
            # que hoy NO es sin horario -por si el encargado cambia el radio.
            editor["capacity_total"] = WALKIN_CUPO_DEFAULT
        cap_total = int(editor["capacity_total"])

        if editor["visibility"] == "walkin":
            editor["derivada"] = (
                f"De {editor['start']} a {editor['end']}, sin horario: hasta "
                f"{cap_total} persona{'s' if cap_total != 1 else ''} por orden "
                f"de llegada.")
        else:
            editor["derivada"] = (
                f"De {editor['start']} a {editor['end']} en franjas de "
                f"{editor['slot_minutes']} minutos: {n} franja{'s' if n != 1 else ''} "
                f"de {cap_franja} persona{'s' if cap_franja != 1 else ''} "
                f"— {n * cap_franja} citas en total.")

        # Las lineas de §6, calculadas EN EL SERVIDOR igual que la de arriba.
        # Dicen la verdad sobre ESTE espacio («tus 10 franjas libres»), no una
        # frase generica: duplicar el calculo en JavaScript es justo lo que el
        # editor evita desde su rediseno.
        # FRANJAS libres, no CITAS libres: `free_slots` devuelve `list[time]`
        # (una entrada por franja con lugar), asi que la rama del espacio nuevo
        # tiene que contar `n` a secas. Con `n * capacity` la frase decia «20
        # franjas libres» para 10 franjas de 2 personas — con cupo 1 coinciden,
        # que es justo lo que hacia pasar al test sin que el numero fuera cierto.
        libres = (len(SlotService.free_slots(db, editor_w)) if editor_w is not None
                  else n)
        # LUGARES libres del SIN HORARIO, no franjas: `free_slots` cuenta
        # franjas (0 o 1 en walkin, nunca "quedan 7"). El cupo total menos las
        # vivas REALES —de cualquier hora, igual que `SlotService.occupancy`—
        # es el mismo numero que veria el egresado si el espacio fuera walkin
        # ahora mismo.
        ocupados_reales = (sum(SlotService.occupancy(db, editor_w).values())
                           if editor_w is not None else 0)
        libres_walkin = max(0, cap_total - ocupados_reales)
        lugar = editor["location"] or "el lugar que pongas arriba"
        editor["vis_lineas"] = {
            "private": "Solo tú agendas en este espacio. El egresado no lo ve.",
            "bookable": (f"El egresado ve tus {libres} "
                         f"franja{'s' if libres != 1 else ''} libre"
                         f"{'s' if libres != 1 else ''} y elige una."),
            "walkin": (f"El egresado ve «{_dia_largo(day)}, {editor['start']} a "
                       f"{editor['end']}, {lugar}» y aparta un lugar "
                       f"(quedan {libres_walkin})."),
        }
    dias_opciones = (_dias_opciones_ctx(db, cohort_id, excluir_iso=day.isoformat())
                     if editor is not None else [])
    return {"dia_id": fila_dia.id, "mios": mios, "ajenos": ajenos,
            "editor": editor, "defaults": defaults, "sin_alcance": sin_alcance,
            "dias_opciones": dias_opciones}


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

    # «reparto» estuvo aqui desde el rediseno de tres pestanas como 4.ª sub-vista
    # candidata y nunca se termino: ninguna rama de `_shell_ctx` le arma `board`,
    # asi que `?v=reparto` escrito a mano daba 500 (`'board' is undefined`).
    # Ningun enlace lo genera y `assign_batch` —el reparto masivo— no tiene
    # llamadores en produccion. Fuera de la lista cae al `else` como cualquier
    # valor basura (`?v=foo` ya funcionaba asi).
    vista = v if v in ("agenda", "atender", "espacios") else "agenda"

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
    #
    # Los tres cubos del universo «sin cita» («Por agendar», «Requieren que les
    # agendes», «Liberaciones pendientes») salen de UN solo calculo en lote
    # (`queue_candidates`, Tarea 7 de 2026-10-04-titulatec-paginacion): antes
    # eran tres llamadas que repetian el universo y preguntaban documentos y
    # cancelaciones candidato por candidato.
    cola = AppointmentService.queue_candidates(db, allowed_program_ids=allowed)
    pendientes = cola["pending"]
    reagendar = AppointmentService.list_reschedule_processes(db, allowed_program_ids=allowed)
    # «Liberaciones pendientes» (spec 2026-10-01-titulatec-biblioteca-caja-
    # design.md §4.4.5; antes «Encuesta sin liberar», D1 de 2026-09-29):
    # documentos aprobados pero le falta alguna LIBERACIÓN según
    # `ClearanceGate` — la encuesta (nunca la envió, o sigue `in_review`/
    # `rejected`) o, donde la convocatoria lo exige, el no adeudo de
    # biblioteca (en Biblioteca o por pagar en Caja). No se puede agendar a
    # nadie de este cubo (la guarda de `AppointmentService.create` lo
    # rechazaría), así que sus filas no llevan navegación ni arrastre — ver
    # `_appt_queue.html`. No entran a `visibles`: no hay ficha que abrirles.
    liberaciones = cola["missing_clearance"]
    # D10: los que agotaron su tope de cancelaciones (D9) y ya NO pueden
    # agendarse solos. Cubo propio y mutuamente excluyente con «Por agendar»:
    # la resta la hace `queue_candidates`, no esta vista.
    bloqueados = cola["blocked"]
    # D5: la fase 02 quedo RECHAZADA, asi que necesitan otra cita. Cubo propio
    # porque, mientras tengan una cita vigente `attended`, quedan fuera del
    # universo «sin cita» del que salen los cubos 1, 2 y 5, y no son `no_show`,
    # asi que «Reagendar» tampoco los veia: sin este cubo no estaban en
    # NINGUNO. Desde el 2026-09-17 TAMBIEN entran SIN cita vigente en absoluto
    # (p.ej. si se cancela esa `attended`): esos SI hace falta sumarlos a
    # `visibles` a mano, porque no tienen cita que los meta por
    # `agenda_process_ids` — ver la union de abajo.
    rechazados = AppointmentService.list_rejected_cotejo_processes(
        db, allowed_program_ids=allowed)
    # Los bloqueados y los rechazados ENTRAN a `visibles`, y no es un detalle:
    # `?selected=` se descarta si el proceso no esta aqui, asi que sin esta
    # union el encargado veria el cubo pero no podria abrirle la ficha a nadie
    # de el — o sea, no podria agendarle, que es lo unico que esos cubos
    # existen para pedirle. Sumar TODOS los rechazados (no solo los sin cita)
    # es deliberado y gratis: quien ya esta en `agenda_process_ids` por su
    # `attended` vigente simplemente se repite en la union de sets.
    #
    # `agenda_ids` se nombra aparte (y no solo inline en la union): el
    # buscador (D8, §4) la vuelve a necesitar para decidir, entre los
    # rechazados, cuales estan "sin cita viva" — sin repetir la consulta.
    agenda_ids = AppointmentService.agenda_process_ids(db, allowed_program_ids=allowed)
    visibles = (agenda_ids | {p.id for p in pendientes} | {p.id for p in bloqueados}
                | {p.id for p in rechazados})
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

    filas_rechazados = _proc_rows_rechazados(db, rechazados)
    # `format_amount` viaja COMO FUNCIÓN (no texto ya formado): la fila de
    # solo lectura del no adeudo (`_appt_attend.html`) pinta distintos montos
    # según `via` (adeudo + donación, total pagado...), mismo patrón que
    # `cashier_body.html`/`library_body.html`.
    from itcj2.apps.titulatec.services.library_clearance_service import format_amount
    ctx = {
        "v": vista, "modo": modo,
        "day": day.isoformat() if day else "",
        "day_largo": _dia_largo(day) if day else "",
        "day_resuelto": day_resuelto,
        "dias": _dias_ctx(db, cohort_id, abierto=day, today=today),
        "detail": detail, "selected_id": selected_id,
        "format_amount": format_amount,
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
        "bloqueados": _proc_rows_bloqueados(db, bloqueados,
                                            cancelaciones=cola["cancellations"]),
        "bloqueados_count": len(bloqueados),
        "reagendar": _proc_rows_reagendar(db, reagendar),
        "reagendar_count": len(reagendar),
        "rechazados": filas_rechazados,
        "rechazados_count": len(rechazados),
        # Lo que suma al badge «por atender»: el rechazado al que le falta
        # alguna LIBERACIÓN no se puede agendar todavía (`SurveyNotSubmitted`
        # / `SurveyNotReleased` / `LibraryNotCleared`), igual que el cubo
        # «Liberaciones pendientes», así que tampoco cuenta como trabajo del
        # encargado.
        "rechazados_accionables_count": sum(
            1 for fila in filas_rechazados if not fila["liberaciones_pendientes"]),
        # No se suma al badge de la pestaña (`appointments_body.html`): ese
        # contador es "por atender" (agendar + reagendar) y este cubo no se
        # puede atender todavía — solo informa.
        "liberaciones": _proc_rows_liberaciones(db, liberaciones),
        "liberaciones_count": len(liberaciones),
        "seleccion": sorted(seleccion or []),
        "page_url": PAGE_URL, "body_url": BODY_URL,
    }

    if vista == "agenda":
        if modo == "resultados":
            ctx["rows"] = _appt_rows(db, AppointmentService.list_appointments(
                db, program_id=program_id, status=estado or None,
                owner_id=user_id if mias else None,
                allowed_program_ids=allowed, q=q))
            # D8: el buscador tambien encuentra a quien no tiene cita. Solo
            # con `q` sin vacio y sin `estado` — un estado de CITA no puede
            # casar con quien no tiene ninguna, asi que con el puesto esta
            # lista siempre saldria vacia; mejor no ofrecerla que ofrecerla
            # siempre en ceros.
            ctx["sin_cita_rows"] = (
                _sin_cita_rows(db, pendientes=pendientes, bloqueados=bloqueados,
                               rechazados=rechazados, liberaciones=liberaciones,
                               agenda_ids=agenda_ids, q=q, program_id=program_id)
                if (q or "").strip() and not estado else [])
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


def _proc_rows_bloqueados(db, procs, *, cancelaciones=None):
    """Filas del cubo de D10, con el conteo que EXPLICA por que estan ahi.

    «3 cancelaciones · ya no puede agendar solo» es lo que convierte una lista
    mas en una instruccion: sin el numero, el encargado no sabe si mirar el
    cubo es urgente o si el alumno simplemente no ha entrado a la pagina.

    El conteo sale de `SelfBookingService.cancellations_map`, el MISMO conteo
    que decide el cubo y que ve el alumno en su pantalla. `cancelaciones`
    ({process_id: n}, opcional): el mapa que `_shell_ctx` ya trae de
    `AppointmentService.queue_candidates`; sin el, se calcula aqui en UNA
    consulta (nunca un COUNT por fila).
    """
    from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService
    filas = _proc_rows(db, procs)
    if cancelaciones is None:
        cancelaciones = SelfBookingService.cancellations_map(db, procs)
    for fila in filas:
        fila["cancelaciones"] = cancelaciones[fila["process_id"]]
    return filas


def _con_liberaciones(db, filas):
    """Suma a cada fila de la cola su estado de LIBERACIONES, en lote
    (`ClearanceGate.status_map`, consultas fijas, nunca una por fila; spec
    2026-10-01-titulatec-biblioteca-caja-design.md §4.4.5):

    * `survey_status` / `library_status` — los de `ClearanceGate.status`,
      para `survey_review_pill` / `library_clearance_pill` (`_macros.html`;
      la de biblioteca no pinta nada con `not_required`).
    * `liberaciones_pendientes` — le falta alguna (`ClearanceGate.blockers`).
      Es lo que decide si la fila se arrastra: abrir un intento con alguna
      pendiente revienta en la guarda dura de `AppointmentService.create`.
    """
    from itcj2.apps.titulatec.services.clearance_gate import ClearanceGate

    if not filas:
        return filas
    estados = ClearanceGate.status_map(db, [fila["process_id"] for fila in filas])
    for fila in filas:
        estado = estados[fila["process_id"]]
        fila["survey_status"] = estado["survey"]
        fila["library_status"] = estado["library"]
        fila["liberaciones_pendientes"] = bool(ClearanceGate.blockers(estado))
    return filas


def _proc_rows_liberaciones(db, procs):
    """Filas del cubo «Liberaciones pendientes» (antes «Encuesta sin
    liberar», D1), con las DOS píldoras: la de la encuesta (la del que nunca
    envió nada dice "Encuesta pendiente", pseudo-estado `missing`; la del que
    la envió, su estado real) y la del no adeudo de biblioteca donde la
    convocatoria lo exige. Varias historias distintas dentro del MISMO cubo, y
    la fila dice cuál le toca a cada quien (`_con_liberaciones`).
    """
    return _con_liberaciones(db, _proc_rows(db, procs))


def _proc_rows_reagendar(db, procs):
    """Filas del cubo «Reagendar», con si sigue teniendo sus LIBERACIONES (I-3).

    Un `no_show` puede seguir aquí mucho después de que se liberaron la
    encuesta y el no adeudo -su cita vieja no se toca (D2 de 2026-09-29, D17
    de 2026-10-01)-, pero REAGENDAR abre un intento NUEVO, y ese vuelve a
    pasar por la guarda dura de `AppointmentService.create`: si GTV revocó la
    liberación o Biblioteca/Caja revirtieron el no adeudo mientras tanto,
    arrastrar esta fila a un lugar libre revienta con `SurveyNotReleased` /
    `LibraryNotCleared`, un error que no explica nada en el contexto de "solo
    no se presentó". Mismo patrón que `_proc_rows_rechazados`
    (`_con_liberaciones`, en lote).
    """
    return _con_liberaciones(db, _proc_rows(db, procs))


def _proc_rows_rechazados(db, procs, *, bloqueados=None):
    """Filas del cubo de D5, con lo que decide si la fila es arrastrable.

    Tres datos por encima de `_proc_rows`:

    * `motivo` — el `rejection_reason` de la fase 02, para que el encargado no
      tenga que abrir la ficha solo para saber que corregir. En lote (1
      consulta): son planas y el volumen es chico, pero N+1 consultas aqui
      serian evitables sin motivo.
    * `survey_status` + `library_status` + `liberaciones_pendientes` — el
      estado real de cada liberación y si le falta alguna (`ClearanceGate`,
      spec 2026-10-01-titulatec-biblioteca-caja-design.md §4.4.5; antes solo
      la encuesta, D1). Importa porque `AppointmentService.create` exige las
      liberaciones antes que cualquier otra cosa (`SurveyNotSubmitted` /
      `SurveyNotReleased` / `LibraryNotCleared`): un proceso puede llegar a
      este cubo sin ellas (nunca envio la encuesta, GTV no la ha liberado, el
      no adeudo sigue en Biblioteca o por pagar; tambien docs/fixtures que
      insertan la cita sin pasar por el service), y arrastrarlo a un lugar
      libre revienta con un error que no explica nada. En lote
      (`_con_liberaciones`).
    * `bloqueado` — el predicado de D9 en lote (`SelfBookingService.
      blocked_map`, la fuente unica que tambien ve el alumno), UNA consulta.
      `bloqueados` ({process_id: bool}, opcional) lo trae ya calculado quien
      lo tenga; sin el, se calcula aqui.

    Los dos primeros no son excluyentes entre si: un rechazado puede tener
    liberaciones PENDIENTES Y estar bloqueado por D9 a la vez, y la plantilla
    pinta las dos senales.
    """
    from itcj2.apps.titulatec.models import ProcessPhase
    from itcj2.apps.titulatec.services.phase_service import PhaseService
    from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService

    por_id = {p.id: p for p in procs}
    filas = _con_liberaciones(db, _proc_rows(db, procs))
    if not filas:
        return filas

    pids = list(por_id)
    motivos = {
        pp.process_id: (pp.rejection_reason or "").strip() or None
        for pp in db.query(ProcessPhase)
                    .filter(ProcessPhase.process_id.in_(pids),
                            ProcessPhase.phase_number == PhaseService.PHASE_COTEJO)
                    .all()
    }
    if bloqueados is None:
        bloqueados = SelfBookingService.blocked_map(db, procs)
    for fila in filas:
        pid = fila["process_id"]
        fila["motivo"] = motivos.get(pid)
        fila["bloqueado"] = bloqueados[pid]
    return filas


def _sin_cita_rows(db, *, pendientes, bloqueados, rechazados, liberaciones,
                   agenda_ids, q, program_id):
    """Filas «Sin cita» del buscador (D8, spec §4): procesos SIN cita viva que
    coinciden con `q`, sobre las listas que `_shell_ctx` YA calculó — sin
    ninguna consulta nueva de citas.

    Cuatro fuentes, las mismas que alimentan la cola (`_appt_queue.html`):
    `pendientes`, `bloqueados` y `rechazados` SIN cita viva entran ABRIBLES
    (están en `visibles`, ver `_shell_ctx`); `agenda_ids` — "con cita vigente
    de CUALQUIER estado" — es justo el predicado que descarta, entre los
    rechazados, a quien SÍ tiene una `attended` vigente esperando dictamen
    (§4 del flujo: ese subconjunto no está "sin cita"). Las tres listas nunca
    se solapan entre sí ni con `rechazados`: `_unscheduled_query` resta
    `rechazados_ids` de su base, así que un proceso no puede caer en dos a la
    vez. «Liberaciones pendientes» (`liberaciones`) entra SIN abrir (no está
    en `visibles`, no hay ficha que darle todavía) y con su `survey_status` y
    `library_status` reales de `ClearanceGate`, para las píldoras — mismo dato
    que ya pinta la cola.

    `casefold` sobre nombre completo, número de control y folio (sin
    mayúsculas). Respeta `program_id` como cualquier otro filtro de la vista.
    """
    from itcj2.apps.titulatec.services.clearance_gate import ClearanceGate

    candidatos = [(p, True) for p in pendientes]
    candidatos += [(p, True) for p in bloqueados]
    candidatos += [(p, True) for p in rechazados if p.id not in agenda_ids]
    candidatos += [(p, False) for p in liberaciones]

    if program_id:
        candidatos = [(p, abrible) for p, abrible in candidatos
                     if p.program_id == program_id]
    if not candidatos:
        return []

    cerrados_ids = [p.id for p, abrible in candidatos if not abrible]
    estados = ClearanceGate.status_map(db, cerrados_ids)

    users, progs = _people(db, [p for p, _ in candidatos])
    aguja = (q or "").strip().casefold()
    salida = []
    for proc, abrible in candidatos:
        u = users.get(proc.student_id)
        prog = progs.get(proc.program_id) if proc.program_id else None
        nombre = u.full_name if u else ""
        control = u.control_number if u else ""
        folio = proc.folio or ""
        if (aguja not in nombre.casefold() and aguja not in control.casefold()
                and aguja not in folio.casefold()):
            continue
        salida.append({
            "process_id": proc.id,
            "folio": proc.folio,
            "student": nombre or "—",
            "control": control or "—",
            "program": prog.name if prog else "Sin carrera",
            "abrible": abrible,
            "survey_status": None if abrible else estados[proc.id]["survey"],
            "library_status": None if abrible else estados[proc.id]["library"],
        })
    return salida


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


@router.post("/{process_id}/atender-ahora", name="titulatec.pages.appointments.attend_now")
def attend_now(
    process_id: int,
    request: Request,
    window_id: str = Form(""),
    user: dict = Depends(require_page_app("titulatec", perms=["titulatec.appointment.api.create"])),
):
    """«Atender ahora» (D7, spec 2026-09-29-titulatec-cotejo-espacios-design.md
    §4): sienta al egresado que esta enfrente en el espacio sin horario de hoy
    del encargado y arranca el cotejo, en una sola transaccion.

    Es `def` y no `async def`, como `move` y `cancel`: el `FOR UPDATE` de
    `SlotService` bloquearia el event loop. Por lo mismo `window_id` llega por
    `Form` (en una `def` no se puede `await request.form()`), y como `str`: un
    valor vacio con tipo entero seria un 422 en vez de la frase del service.

    Responde el shell en `v=atender&selected={pid}` —lo trae el querystring
    del formulario de la ficha, con el dia de hoy— con «Cotejo iniciado.». El
    doble clic lo absorbe `create`: el segundo POST encuentra la cita viva
    (`AppointmentConflict`, colision de estado) y responde 200 con la ficha
    fresca y el aviso. Una sola cita (Review Focus 4).
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.appointment_service import AppointmentService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    uid = int(user["sub"])
    wid = _to_int(window_id)
    db = SessionLocal()
    try:
        assert_process_in_scope(db, uid, process_id)
        return _accion(request, db, selected_id=process_id, user_id=uid,
                       fn=lambda: AppointmentService.attend_now(
                           db, process_id, window_id=wid, actor_id=uid),
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
      (la encuesta de egresados, que libera GTV, y el no adeudo de biblioteca,
      que liberan Biblioteca y Caja) y marcarlos a mano romperia la
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


# ===========================================================================
# Respaldo «Constancia previa…» / «Deshacer» del no adeudo de biblioteca (D9)
# ===========================================================================
# Servicios Escolares, desde el panel de atender (gemelas en
# `pages/admin.py` para el expediente). Van por `{process_id}` con
# `assert_process_in_scope` como PRIMERA sentencia del `try` (censo de
# `test_scope_guard.py`, spec §5 invariante 6).

@router.post("/{process_id}/no-adeudo-previo",
             name="titulatec.pages.appointments.library_prior")
async def library_prior(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app(
        "titulatec", perms=["titulatec.library_clearance.api.prior"])),
):
    """SE registra, desde el panel de atender, que el egresado YA trae su
    constancia previa de no adeudo (D9): `pending`/`awaiting_payment` ->
    `cleared/prior`, sin pasar por Caja. Gemela de `pages/admin.py::
    process_library_prior`."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope
    from itcj2.apps.titulatec.utils.form_dates import parse_issued_on

    form = dict(await request.form())
    note = form.get("note") or None
    uid = int(user["sub"])
    db = SessionLocal()
    try:
        assert_process_in_scope(db, uid, process_id)
        try:
            issued_on = parse_issued_on(form.get("issued_on"))
            clearance = LibraryClearanceService.for_process_locked(db, process_id)
            LibraryClearanceService.register_prior(
                db, clearance.id, uid, issued_on=issued_on, note=note,
                by="school_services")
        except LookupError:
            return Response(status_code=404)
        except ValueError as exc:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
        return _render_body(request, db, selected_id=process_id, user_id=uid,
                            **_action_ctx(request))
    finally:
        db.close()


@router.post("/{process_id}/no-adeudo-previo/deshacer",
             name="titulatec.pages.appointments.library_prior_undo")
async def library_prior_undo(
    process_id: int,
    request: Request,
    user: dict = Depends(require_page_app(
        "titulatec", perms=["titulatec.library_clearance.api.prior"])),
):
    """Deshace la constancia previa (motivo obligatorio): `cleared/prior` ->
    `pending`. Gemela de `pages/admin.py::process_library_prior_undo`."""
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.library_clearance_service import LibraryClearanceService
    from itcj2.apps.titulatec.services.scope_service import assert_process_in_scope

    form = dict(await request.form())
    reason = form.get("reason") or ""
    uid = int(user["sub"])
    db = SessionLocal()
    try:
        assert_process_in_scope(db, uid, process_id)
        try:
            clearance = LibraryClearanceService.for_process_locked(db, process_id)
            LibraryClearanceService.undo_prior(db, clearance.id, uid, reason)
        except LookupError:
            return Response(status_code=404)
        except ValueError as exc:
            return Response(status_code=400, headers={"X-Tt-Error": _hdr(str(exc))})
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
    from itcj2.apps.titulatec.services.review_window_service import ReviewWindowService
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
        # M-5 (revisión final): «Apartarle lugar»/«Mover aquí» (_appt_board.html)
        # pegan a ESTA misma ruta con `slot=` la APERTURA del sin horario, y el
        # toast genérico («Cita agendada/movida») engaña -no hay una CITA a esa
        # hora, hay un LUGAR apartado por orden de llegada, D4/D11-. `cuando`
        # sigue siendo la hora sola (aquí, la apertura), nunca el rango
        # `inicio-fin` del espacio: eso es lo que ANUNCIA el tablero
        # (`g.horario`), no lo que le pasó a ESTE alumno.
        w = ReviewWindowService.get(db, window_id) if window_id else None
        sin_horario = bool(w) and w.visibility == "walkin"
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
            mensaje = (f"Lugar apartado a las {cuando}. Se avisó al alumno."
                      if sin_horario else
                      f"Cita agendada a las {cuando}. Se avisó al alumno.")
            return _accion(request, db, selected_id=process_id, user_id=uid,
                           fn=lambda: AppointmentService.create(
                               db, process_id, window_id=window_id, slot_start=slot,
                               created_by_id=uid),
                           exito=mensaje)
        mensaje = (f"Movido a las {cuando}. Se avisó al alumno." if sin_horario
                  else f"Cita movida a las {cuando}. Se avisó al alumno.")
        return _accion(request, db, selected_id=process_id, user_id=uid,
                       fn=lambda: AppointmentService.reschedule(
                           db, appt, window_id=window_id, slot_start=slot, actor_id=uid),
                       exito=mensaje)
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
        proc = assert_process_in_scope(db, int(user["sub"]), process_id)
        doc = DocumentService.get_document(db, process_id, type_code)
        if not doc:
            return Response(status_code=404)
        path = storage.abs_path(doc.file_path)
        mime = doc.mime_type
        # Mismo nombre que la bandeja de Documentos: `{control}_{ETIQUETA}.{ext}`.
        _period, control = DocumentService._storage_keys(db, proc)
        filename = storage.download_filename(control, type_code, doc.file_path)
    finally:
        db.close()
    if not path.exists():
        return Response(status_code=404)
    return FileResponse(str(path), media_type=mime,
                        headers={"Content-Disposition": f'inline; filename="{filename}"'})


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
    from itcj2.core.services.authz_cache import cached_perms
    try:
        perms = cached_perms(db, user_id, "titulatec")
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

    `exito` es un texto fijo, O UN CALLABLE que recibe lo que devolvió `fn()` y
    regresa `(mensaje, kind)`. Hace falta para D9: el aviso «Espacio creado en
    N días, se saltaron M» no se puede fijar ANTES de correr `fn` porque N y M
    SON el resultado. Los llamadores que ya existían (pausar, borrar, guardar
    sin días nuevos) siguen pasando un texto fijo y no notan el cambio.
    """
    from itcj2.apps.titulatec.services.appointment_errors import (
        AppointmentError, SlotLockTimeout,
    )
    try:
        resultado = fn()
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
        mensaje, kind = exito(resultado) if callable(exito) else (exito, kind)
        resp.headers["X-Tt-Notice"] = _hdr(mensaje)
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
    capacity_total: str = Form(""),
    location: str = Form(""),
    visibility: str = Form("private"),
    dias: list[str] = Form(default=[]),
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

    `capacity_total` es el cupo TOTAL de un espacio sin horario (D3); con
    franjas se sigue usando `capacity`, el de siempre. El servidor decide cuál
    de los dos CUENTA según `visibility` — el que no aplica viaja igual en el
    formulario (oculto por CSS, nunca por `type=hidden`), porque HTML5 lo
    sigue validando aunque esté oculto. Un `capacity_total` explícito fuera de
    `[1, WALKIN_TOPE]` (100, D12) es 400: hoy el `max` del HTML es lo único
    que lo frena, y un formulario armado a mano (o una pestaña vieja con el
    `max` de antes, 500) lo saltaría en silencio. Al ACTUALIZAR el techo real
    es `max(WALKIN_TOPE, w.capacity)` (Arreglo 1): nunca obliga a bajar de lo
    que el espacio YA tiene, aunque la red de seguridad de la migración
    (`GREATEST(30, vivas)`) lo haya dejado por encima de 100.

    `dias` (D9) son fechas ISO adicionales, SOLO en `window_id == "nuevo"`: el
    día de la URL (`?date=`) siempre se crea, pase lo que pase en `dias`.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
    from itcj2.apps.titulatec.services.review_window_service import (
        ReviewWindowService, WALKIN_CUPO_DEFAULT, WALKIN_TOPE)
    from itcj2.apps.titulatec.services.scope_service import _program_ids_for_user

    if visibility not in _VISIBILIDADES:
        return Response(status_code=400, headers={
            "X-Tt-Error": _hdr("Ese modo de visibilidad no existe.")})

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        # `capacity` efectiva (D3, spec §3.2): sin horario captura el cupo
        # TOTAL en «Personas en total»; con franjas, el de siempre («Personas
        # por franja»).
        #
        # M-6 (revisión final): una PESTAÑA VIEJA -abierta antes de este
        # deploy, blue/green (spec §7.3.4)- no conoce `capacity_total`: su
        # formulario sigue mandando solo `capacity`, con la semántica de
        # ANTES (por franja), y ese campo llega VACÍO. Tratarlo como cupo
        # TOTAL sería catastrófico: al actualizar, `_to_int("") or 1`
        # resetearía a 1 un espacio que ya tenía «Abrir más lugares»
        # acumulados; al crear, nacería con un solo lugar en vez del default
        # PLANO. Al ACTUALIZAR se conserva el `capacity` que la fila YA
        # tiene (nadie lo tocó); al CREAR nace en `WALKIN_CUPO_DEFAULT` (30,
        # D12) -ya NO «franjas × cupo por franja»: esa semántica se retiró
        # junto con el tope de 500- para que un alta desde una pestaña vieja
        # no herede un número que ya nadie prometió.
        capacity_total_raw = (capacity_total or "").strip()
        if visibility == "walkin" and not capacity_total_raw:
            if window_id == "nuevo":
                capacidad_cruda = str(WALKIN_CUPO_DEFAULT)
            else:
                w_actual = ReviewWindowService.get(db, _to_int(window_id))
                capacidad_cruda = str(w_actual.capacity) if w_actual else capacity
        elif visibility == "walkin":
            # Entrada EXPLÍCITA (pestaña ya actualizada): 1..`WALKIN_TOPE`,
            # el mismo rango que el `max` del editor (D12). Hoy solo lo frena
            # ese `max` del HTML -saltable a mano-, así que se revisa también
            # aquí, igual que `visibility` arriba (mejor una frase que el
            # `CheckConstraint` de más abajo en la validación de agenda).
            #
            # Arreglo 1 (ronda de revisión del cambio cupo 30/100): al
            # ACTUALIZAR, el techo real es `max(WALKIN_TOPE, w.capacity)`, NO
            # `WALKIN_TOPE` a secas. La red de seguridad de la migración
            # (`GREATEST(30, vivas)`) puede dejar un walkin con más de 100
            # citas vivas; los DOS campos de cupo viven siempre en el DOM
            # (D3), así que CUALQUIER guardado de ese espacio -aunque solo
            # cambie el lugar- manda de vuelta su propio `capacity_total`. Sin
            # este techo dinámico ese número por sí solo ya rebasaba
            # `WALKIN_TOPE` y el 400 dejaba el espacio IMPOSIBLE de
            # re-guardar para siempre, para cualquier campo. Nunca obliga a
            # BAJAR de lo que ya tiene. Al CREAR no hay `w.capacity` previo,
            # así que el techo sigue siendo `WALKIN_TOPE` a secas. El mensaje
            # de 400 NO cambia: sigue anunciando el rango normal (1-100), que
            # es el que aplica salvo este caso raro.
            techo = WALKIN_TOPE
            if window_id != "nuevo":
                w_actual = ReviewWindowService.get(db, _to_int(window_id))
                if w_actual is not None:
                    techo = max(WALKIN_TOPE, w_actual.capacity)
            cupo_val = _to_int(capacity_total)
            if cupo_val is None or not (1 <= cupo_val <= techo):
                return Response(status_code=400, headers={
                    "X-Tt-Error": _hdr(
                        "El cupo de un espacio sin horario va de 1 a "
                        f"{WALKIN_TOPE} personas.")})
            capacidad_cruda = capacity_total
        else:
            capacidad_cruda = capacity
        campos = dict(
            start_time=start_time, end_time=end_time,
            slot_minutes=_to_int(slot_minutes) or 30,
            capacity=_to_int(capacidad_cruda) or 1,
            location=(location or None),
            visibility=visibility,
        )
        # Ruling 14: `offer` es fail-closed, asi que un espacio PUBLICADO -
        # `bookable` O `walkin`, los dos se ofrecen (revisión final, M-3)- de
        # alguien sin carreras asignadas no se lo ofrece a NADIE. Se guarda
        # igual —el predicado no cambia—, pero callarlo convierte un espacio
        # publicado en un bug silencioso: el encargado cree que publico y no
        # publico nada.
        avisa_sin_alcance = (visibility in ("bookable", "walkin")
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

            # D9: además del día de la URL, los que se hayan marcado en
            # «También en estos días». Solo los VALIDOS (convocatoria activa,
            # abiertos, >= hoy) — las mismas casillas que ofreció el editor:
            # un día que se cerró entre el render y el POST se ignora en
            # silencio, no truena.
            extra_ids = [i for i in _dias_ids_por_iso(db, cohort_id, dias)
                        if i != fila.id]
            day_ids = [fila.id] + extra_ids

            def _crear():
                return ReviewWindowService.create_many(
                    db, day_ids, uid, position_id=pos, actor_id=uid, **campos)

            def _aviso(resultado):
                creados, saltados = resultado
                n = len(creados)
                partes = [f"Espacio creado en {n} día{'s' if n != 1 else ''}."]
                extra = _mensaje_dias_saltados(saltados)
                if extra:
                    partes.append(extra)
                if avisa_sin_alcance:
                    partes.append(
                        "NINGÚN egresado lo verá: no tienes carreras asignadas. "
                        "Pídele a la jefatura de Servicios Escolares que te "
                        "asigne las que atiendes.")
                return " ".join(partes), (
                    "warning" if (saltados or avisa_sin_alcance) else "success")

            return _accion_espacio(request, db, user_id=uid, fn=_crear,
                                   exito=_aviso, kind=kind)
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


@router.post("/espacios/{window_id}/lugares", name="titulatec.pages.appointments.space_places")
def space_places(
    window_id: int,
    request: Request,
    n: str = Form(""),
    user: dict = Depends(require_page_app("titulatec", perms=_ESPACIO_PERMS)),
):
    """«Abrir más lugares» (D6): +N al cupo TOTAL de un espacio SIN HORARIO,
    desde el tablero de la Agenda (`_appt_board.html`).

    `n` llega como `str` y no como `int`, como `window_id` en `atender-ahora`:
    un valor vacío o basura con tipo entero sería un 422 en vez de la frase de
    `PlacesOutOfRange`. `ReviewWindowService.add_places` valida el rango
    (1-50), el tope total (100, D12) y que el espacio SEA sin horario; todo eso son
    errores de ENTRADA (400), salvo el timeout del lock. El mensaje de éxito
    usa el valor YA aceptado por el servicio, así que solo se lee si `fn()` no
    reventó — un `n` que no se pudo interpretar nunca llega a mostrarse.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.review_window_service import ReviewWindowService

    uid = int(user["sub"])
    n_val = _to_int(n)
    db = SessionLocal()
    try:
        w = _espacio_en_alcance(db, window_id, uid)
        return _accion_espacio(
            request, db, user_id=uid,
            fn=lambda: ReviewWindowService.add_places(db, w, n_val),
            exito=f"Listo: {n_val} lugar{'es' if n_val != 1 else ''} más.")
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
    dias: list[str] = Form(default=[]),
    user: dict = Depends(require_page_app("titulatec", perms=_ESPACIO_PERMS)),
):
    """Replica el horario en los días ELEGIDOS (D9, spec §0.2 y §5).

    Antes copiaba a TODOS los días de la convocatoria y saltaba cualquiera
    donde el dueño YA tuviera un espacio, aunque no chocara con el horario que
    se copiaba: «copiar a los demás días» pisaba en silencio la elección de
    dejar un hueco. Ahora el encargado elige los días con casillas, y solo se
    salta el que de verdad se ENCIMA.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.review_window_service import ReviewWindowService

    if not dias:
        return Response(status_code=400, headers={
            "X-Tt-Error": _hdr("Elige al menos un día.")})

    uid = int(user["sub"])
    db = SessionLocal()
    try:
        w = _espacio_en_alcance(db, window_id, uid)
        cohort_id = _active_cohort_id(db)
        day_ids = _dias_ids_por_iso(db, cohort_id, dias) if cohort_id else []

        # Colisión de estado, no error de entrada (ronda de arreglo 1): el
        # formulario SÍ traía casillas marcadas (si no, ya habría salido el
        # 400 de arriba), pero entre el render del editor y este POST TODAS
        # esas fechas dejaron de ser válidas -- el día se cerró, o ya pasó.
        # Sin este corte, `copy_to_days(db, w, [])` devuelve `([], [])` sin
        # tocar nada y el aviso de abajo lo anunciaría como «Horario copiado
        # a 0 días.» con tono de ÉXITO: un no-op disfrazado. Se corta ANTES
        # de llamar al servicio, con el mismo par de headers que arma
        # `_accion_espacio` para una colisión de estado (200 + cuerpo fresco).
        if not day_ids:
            resp = _render_body(request, db, selected_id=None, user_id=uid,
                                **_action_ctx(request))
            resp.headers["X-Tt-Notice"] = _hdr(
                "Ninguno de los días que elegiste sigue abierto para cotejo. "
                "Revisa la lista y vuelve a intentar.")
            resp.headers["X-Tt-Notice-Kind"] = "warning"
            return resp

        def _aviso(resultado):
            creados, saltados = resultado
            n = len(creados)
            partes = [f"Horario copiado a {n} día{'s' if n != 1 else ''}."]
            extra = _mensaje_dias_saltados(saltados)
            if extra:
                partes.append(extra)
            return " ".join(partes), ("warning" if saltados else "success")

        return _accion_espacio(
            request, db, user_id=uid,
            fn=lambda: ReviewWindowService.copy_to_days(db, w, day_ids),
            exito=_aviso)
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
