"""Citas de cotejo de documentos (fase 2, Servicios Escolares).

Una cita VIGENTE por proceso, más el historial de los intentos anteriores (ver
abajo). El encargado de la carrera agenda, reagenda, cancela y marca el cotejo;
el alumno confirma, solicita un cambio o cancela. Los cambios relevantes
escriben un ``ProcessEvent`` (phase_number=2). El commit vive aquí.

Estados de ``ReviewAppointment.status``::

    scheduled    agendada, pendiente de confirmación del alumno
    confirmed    el alumno confirmó asistencia
    in_progress  el encargado está atendiendo el cotejo
    attended     cotejo concluido (la fase se aprueba aparte)   [terminal]
    no_show      el alumno no se presentó
    cancelled    se canceló y el lugar volvió al pozo (D12)     [terminal]
    superseded   la reemplazó el intento siguiente              [terminal]

Historial de intentos: ``is_current`` es un eje APARTE de ``status``
--------------------------------------------------------------------
Un proceso tiene como mucho una cita **vigente** (``is_current``), y las
anteriores se conservan. Confundir los dos ejes es el error fácil:

* reagendar una cita **activa** la pasa a ``superseded`` e inserta otra;
* abrir un intento nuevo tras ``no_show`` / ``attended`` / ``cancelled``
  **conserva el status de la fila vieja** (un ``no_show`` sigue diciendo
  ``no_show``, ocupando su franja — D10) y solo le quita ``is_current``.

Por eso ``get_for_process`` devuelve **la vigente** y no «la última por id»:
con historial, «la última» devolvería intentos ya superados. Y por eso los
listados de la agenda filtran ``is_current``: sin ese filtro pintarían cada
intento superado como una cita más.

La matriz de transiciones se valida ANTES de escribir
-----------------------------------------------------
Ninguno de los métodos miraba el estado previo, así que ``no_show → attended``
era alcanzable, y ``scheduled → attended`` se saltaba el cotejo entero. Ahora
hay una matriz explícita y `attended` es **terminal**.

`no_show → in_progress` sí es legal, y tiene nombre propio en la UI:
«Deshacer no se presentó». Es un error de dedo con consecuencias para un
egresado, así que se puede corregir, pero no en silencio.

El guard de día vive aquí, no en la página
-------------------------------------------
`ReviewDayService.assert_allowed` se invocaba desde `pages/`, así que cualquier
otro llamador de este service escribía sin validar. Y peor: la comprobación
estaba condicionada a que la fecha se hubiera podido parsear, así que sin hora
no se validaba, **no se creaba nada** y la ruta respondía 200 con el cuerpo
re-renderizado. El encargado pulsaba «Agendar» y no pasaba nada, sin un solo
mensaje. Ahora falta de datos es `MissingSchedule`.

La hora la pone `SlotService`
------------------------------
`create` y `reschedule` reciben **ventana y franja**, no un `datetime` libre.
Es lo que hace que el cupo duro no sea evadible: mientras existiera un camino
que aceptara fecha y hora sueltas, bastaba con no pasar por el que valida.
"""
from __future__ import annotations

from datetime import datetime, time

from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.appointment_errors import (
    AppointmentConflict, InvalidTransition,
)
from itcj2.core.utils.timezone import db_now

# Estados "vivos" de una cita (D4): mientras el proceso tenga una en uno de
# estos, no se le puede abrir otra. Gemelo de `slot_service._ESTADOS_ACTIVOS`,
# que decide lo complementario (si la fila vieja pasa a `superseded` o
# conserva su status al abrir el intento nuevo). Son la misma regla vista
# desde los dos lados; si algún día divergen, es un bug.
_ESTADOS_ACTIVOS: frozenset[str] = frozenset({"scheduled", "confirmed", "in_progress"})

# Estados desde los que `reschedule` puede mover al alumno a otra franja.
# NO es la matriz: reagendar a un `no_show` no transiciona nada —su fila se
# queda en `no_show` ocupando su franja (D7 + D10)— sino que abre un intento
# nuevo. `in_progress` queda fuera a propósito (un cotejo empezado se cierra
# con `attended` o `no_show`, §2.3) y los tres terminales también: mover una
# `attended` borraría la evidencia de que el cotejo ocurrió.
_REAGENDABLES: frozenset[str] = frozenset({"scheduled", "confirmed", "no_show"})


class AppointmentService:
    # Matriz de transiciones DENTRO de un mismo intento (spec 2026-09-15 §2.3).
    # `scheduled` no es destino de ninguna: abrir un intento nuevo crea una
    # fila, no reescribe la que había, así que dejó de ser una transición.
    # Tres terminales: `attended`, `cancelled` y `superseded`.
    _TRANSICIONES: dict[str, set[str]] = {
        "scheduled":   {"confirmed", "in_progress", "no_show", "cancelled", "superseded"},
        "confirmed":   {"in_progress", "no_show", "cancelled", "superseded"},
        "in_progress": {"attended", "no_show"},
        "no_show":     {"in_progress"},
        "attended":    set(),
        "cancelled":   set(),
        "superseded":  set(),
    }

    @staticmethod
    def assert_transition(desde: str | None, hacia: str) -> None:
        """Levanta `InvalidTransition` si el salto no está permitido."""
        permitidos = AppointmentService._TRANSICIONES.get(desde or "scheduled", set())
        if hacia not in permitidos:
            raise InvalidTransition(desde=desde, hacia=hacia)

    # ---------------------------------------------------------------- lecturas
    @staticmethod
    def get_for_process(db: Session, process_id: int):
        """La cita **VIGENTE** del proceso (o None).

        Antes era «la más reciente por id», que sin historial era lo mismo.
        Con historial NO lo es: devolvería intentos ya superados o cancelados.
        El índice único parcial `uq_titulatec_review_appt_current` garantiza
        que como mucho hay una vigente, así que el `.first()` no esconde un
        empate — y por eso tampoco necesita `order_by`.

        Un proceso cuya única cita se canceló devuelve `None`, que es
        justamente lo que hace que vuelva a estar «sin cita» y pueda agendar
        otra (D6).
        """
        from itcj2.apps.titulatec.models import ReviewAppointment
        return (
            db.query(ReviewAppointment)
            .filter_by(process_id=process_id, is_current=True)
            .first()
        )

    @staticmethod
    def list_attempts(db: Session, process_id: int) -> list:
        """Todos los intentos del proceso, del más reciente al más viejo.

        La contraparte de `get_for_process`: aquella devuelve UNA fila (la
        vigente), ésta el historial completo — superados, cancelados y el
        vigente. La consumen la ficha de Atender y el expediente; sin ella el
        encargado no tiene forma de ver que ésta es la tercera vez que se le
        agenda a alguien.
        """
        from itcj2.apps.titulatec.models import ReviewAppointment
        return (
            db.query(ReviewAppointment)
            .filter_by(process_id=process_id)
            .order_by(ReviewAppointment.attempt_no.desc(),
                      ReviewAppointment.id.desc())
            .all()
        )

    @staticmethod
    def list_appointments(db: Session, *, program_id: int | None = None,
                          status: str | None = None, owner_id: int | None = None,
                          allowed_program_ids: set | None = None,
                          q: str | None = None) -> list:
        """Citas de la agenda, ordenadas por fecha. Filtros opcionales.

        `allowed_program_ids`: None = sin restricción de carrera; set vacío = [].
        `q`: busca por nombre del alumno o número de control, DENTRO del alcance.
        """
        from itcj2.apps.titulatec.models import ReviewAppointment, TitulationProcess
        from itcj2.core.models.user import User
        if allowed_program_ids is not None and len(allowed_program_ids) == 0:
            return []
        query = (
            db.query(ReviewAppointment)
            .join(TitulationProcess, ReviewAppointment.process_id == TitulationProcess.id)
            # Solo la cita VIGENTE de cada proceso: sin esto la agenda pinta
            # cada intento superado como una cita más y el mismo alumno sale
            # repetido.
            .filter(ReviewAppointment.is_current.is_(True))
        )
        if allowed_program_ids is not None:
            query = query.filter(TitulationProcess.program_id.in_(allowed_program_ids))
        if program_id:
            query = query.filter(TitulationProcess.program_id == program_id)
        if status:
            query = query.filter(ReviewAppointment.status == status)
        if owner_id:
            query = query.filter(ReviewAppointment.created_by_id == owner_id)
        if q and q.strip():
            from sqlalchemy import func, or_
            aguja = f"%{q.strip()}%"
            nombre = func.concat(func.coalesce(User.first_name, ""), " ",
                                 func.coalesce(User.last_name, ""))
            query = (query.join(User, User.id == TitulationProcess.student_id)
                     .filter(or_(User.control_number.ilike(aguja),
                                 nombre.ilike(aguja),
                                 TitulationProcess.folio.ilike(aguja))))
        return query.order_by(ReviewAppointment.scheduled_at).all()

    @staticmethod
    def counts_by_day(db: Session, start, end, *, allowed_program_ids: set | None = None) -> dict:
        """{date: n_citas} en [start, end) (datetimes), acotado por carrera."""
        from itcj2.apps.titulatec.models import ReviewAppointment, TitulationProcess
        if allowed_program_ids is not None and len(allowed_program_ids) == 0:
            return {}
        q = (db.query(ReviewAppointment)
             .join(TitulationProcess, ReviewAppointment.process_id == TitulationProcess.id)
             # Solo la vigente: un intento superado inflaría el contador del
             # carril de días con una cita que ya no existe.
             .filter(ReviewAppointment.is_current.is_(True))
             .filter(ReviewAppointment.scheduled_at >= start, ReviewAppointment.scheduled_at < end))
        if allowed_program_ids is not None:
            q = q.filter(TitulationProcess.program_id.in_(allowed_program_ids))
        out = {}
        for a in q.all():
            d = a.scheduled_at.date()
            out[d] = out.get(d, 0) + 1
        return out

    @staticmethod
    def list_for_day(db: Session, day, *, allowed_program_ids: set | None = None) -> list:
        """Citas cuyo scheduled_at cae en el día `day` (date), ordenadas por hora.

        allowed_program_ids: None = sin restricción; set vacío = devuelve [].
        """
        from datetime import datetime as _dt, time as _t, timedelta
        from itcj2.apps.titulatec.models import ReviewAppointment, TitulationProcess
        if allowed_program_ids is not None and len(allowed_program_ids) == 0:
            return []
        start = _dt.combine(day, _t.min)
        end = start + timedelta(days=1)
        q = (
            db.query(ReviewAppointment)
            .join(TitulationProcess, ReviewAppointment.process_id == TitulationProcess.id)
            # Solo la vigente (ver `list_appointments`): el tablero del día
            # sentaría dos veces al mismo alumno, una por intento.
            .filter(ReviewAppointment.is_current.is_(True))
            .filter(ReviewAppointment.scheduled_at >= start,
                    ReviewAppointment.scheduled_at < end)
        )
        if allowed_program_ids is not None:
            q = q.filter(TitulationProcess.program_id.in_(allowed_program_ids))
        return q.order_by(ReviewAppointment.scheduled_at).all()

    @staticmethod
    def agenda_process_ids(db: Session, *, allowed_program_ids: set | None = None) -> set:
        """`{process_id}` de TODA la agenda del usuario, sin filtros de vista.

        Es el universo acotado contra el que la pagina valida el `?selected=`:
        una sola consulta de una sola columna, para no tener que materializar la
        agenda entera solo por comprobar si un id es alcanzable. Deliberadamente
        NO acepta `status`/`owner_id`/`program_id`: si se estrechara con los
        filtros de la vista, abrir a un alumno dejaria de funcionar en cuanto el
        usuario tuviera un filtro puesto.

        allowed_program_ids: None = sin restriccion; set vacio = devuelve set().
        """
        from itcj2.apps.titulatec.models import ReviewAppointment, TitulationProcess
        if allowed_program_ids is not None and len(allowed_program_ids) == 0:
            return set()
        q = (
            db.query(ReviewAppointment.process_id)
            .join(TitulationProcess, ReviewAppointment.process_id == TitulationProcess.id)
            # Mismo criterio que el resto de la agenda: el universo del
            # `?selected=` es el de las citas VIGENTES. Un proceso cuya única
            # cita se canceló ya no está en la agenda — llega por «Por
            # agendar», que es la otra mitad de este universo.
            .filter(ReviewAppointment.is_current.is_(True))
        )
        if allowed_program_ids is not None:
            q = q.filter(TitulationProcess.program_id.in_(allowed_program_ids))
        return {pid for (pid,) in q.distinct()}

    @staticmethod
    def _unscheduled_query(db: Session, *, program_id: int | None,
                           allowed_program_ids: set | None):
        """Base compartida de `list_pending_processes` y
        `list_missing_survey_processes`: procesos activos, SIN cita, acotados
        por carrera. Cada llamador le agrega su propio predicado de la
        solicitud (existe / no existe) y el filtro de documentos, para no
        arriesgarse a que los dos cubos se desincronicen del universo que
        comparten.

        `None` si `allowed_program_ids` cerró el alcance (set vacío): el
        llamador debe leerlo así y devolver `[]` sin más consultas.
        """
        from itcj2.apps.titulatec.models import ReviewAppointment, TitulationProcess
        if allowed_program_ids is not None and len(allowed_program_ids) == 0:
            return None
        # «Sin cita» significa sin cita VIGENTE, no «sin ninguna fila jamás».
        # Sin este filtro, un alumno que canceló (D6: puede agendar otra) no
        # volvía a «Por agendar» — y como `_shell_ctx` arma
        # `visibles = agenda_process_ids | pendientes` y descarta el
        # `?selected=` que no esté ahí, el encargado ni siquiera podía abrirle
        # la ficha: no era invisible, era inalcanzable.
        with_appt = [pid for (pid,) in
                     db.query(ReviewAppointment.process_id)
                     .filter(ReviewAppointment.is_current.is_(True))
                     .distinct()]
        q = db.query(TitulationProcess).filter(TitulationProcess.status == "active")
        if with_appt:
            q = q.filter(~TitulationProcess.id.in_(with_appt))
        if allowed_program_ids is not None:
            q = q.filter(TitulationProcess.program_id.in_(allowed_program_ids))
        if program_id:
            q = q.filter(TitulationProcess.program_id == program_id)
        return q

    @staticmethod
    def _pending_candidates(db: Session, *, program_id: int | None,
                            allowed_program_ids: set | None) -> list:
        """Procesos activos, SIN cita vigente, con los 3 documentos iniciales
        aprobados y con la SOLICITUD de liberación de la encuesta de egresados
        ya abierta (D2: hace falta que la haya enviado, no que GTV ya la haya
        liberado).

        De aquí salen DOS cubos que se reparten el conjunto sin solaparse
        (§6): «Por agendar» y «Requieren que les agendes» (los bloqueados por
        D9). Se calcula en un solo sitio para que no puedan desincronizarse:
        con dos consultas gemelas, un proceso acabaría en los dos cubos o en
        ninguno según cuál se tocara primero.

        Los `no_show` NO entran: conservan su cita y su lugar («si no se
        presentó es que ya pasó») y viven en `list_reschedule_processes`.
        Quien SÍ tiene los 3 documentos pero todavía no envía la encuesta vive
        en `list_missing_survey_processes`.
        """
        from itcj2.apps.titulatec.models import SurveyReview, TitulationProcess
        from itcj2.apps.titulatec.services.document_service import DocumentService
        q = AppointmentService._unscheduled_query(
            db, program_id=program_id, allowed_program_ids=allowed_program_ids)
        if q is None:
            return []
        q = q.filter(db.query(SurveyReview.id)
                    .filter(SurveyReview.process_id == TitulationProcess.id)
                    .exists())
        candidates = q.order_by(TitulationProcess.created_at).all()
        return [p for p in candidates if DocumentService.initial_docs_all_approved(db, p.id)]

    @staticmethod
    def list_pending_processes(db: Session, *, program_id: int | None = None,
                               allowed_program_ids: set | None = None) -> list:
        """«Por agendar»: los del universo de arriba que TODAVÍA pueden
        agendarse solos (o esperar a que el encargado los siente).

        **Excluye a los bloqueados por D9**, que se van a su propio cubo
        (`list_self_blocked_processes`). Los cuatro cubos de la cola son
        mutuamente excluyentes (§6): sin esta resta, el bloqueado sale en dos
        sitios a la vez y el encargado no sabe cuál mirar — ni cuál de los dos
        contadores le está diciendo la verdad.

        El tope lo decide `SelfBookingService`, que es donde vive la regla del
        alumno (D13), en vez de una consulta propia aquí.
        """
        from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService
        return [p for p in AppointmentService._pending_candidates(
                    db, program_id=program_id, allowed_program_ids=allowed_program_ids)
                if not SelfBookingService.is_blocked_by_cancellations(db, p)]

    @staticmethod
    def list_self_blocked_processes(db: Session, *, program_id: int | None = None,
                                    allowed_program_ids: set | None = None) -> list:
        """«Requieren que les agendes» — el cubo de D10.

        Mismo universo que «Por agendar» con el ÚNICO predicado añadido de D9:
        cancelaron su cita tantas veces que perdieron el auto-agendado. El
        encargado TIENE que verlos claramente, y por eso son un cubo propio y
        no una fila más del montón: nadie los va a agendar si nadie sabe que
        están esperando a que alguien lo haga por ellos.

        El criterio es el mismo objeto que usa la pantalla del alumno
        (`SelfBookingService.is_blocked_by_cancellations`, la regla 5 de §3):
        con dos implementaciones, este cubo diría una cosa y el alumno vería
        otra.
        """
        from itcj2.apps.titulatec.services.self_booking_service import SelfBookingService
        return [p for p in AppointmentService._pending_candidates(
                    db, program_id=program_id, allowed_program_ids=allowed_program_ids)
                if SelfBookingService.is_blocked_by_cancellations(db, p)]

    @staticmethod
    def list_missing_survey_processes(db: Session, *, program_id: int | None = None,
                                      allowed_program_ids: set | None = None) -> list:
        """Procesos activos, SIN cita, con los 3 documentos aprobados, pero
        SIN la solicitud de liberación de la encuesta de egresados (D2).

        Mismo universo y alcance que `list_pending_processes` — misma base
        (`_unscheduled_query`) y mismo filtro de documentos — con el ÚNICO
        predicado invertido: aquí la solicitud NO existe. Alimenta el cubo
        «Sin encuesta» de la cola: nadie se agenda sin haberla enviado, así
        que a este grupo no le sirve un lugar libre, le sirve saber que falta
        la encuesta.
        """
        from itcj2.apps.titulatec.models import SurveyReview, TitulationProcess
        from itcj2.apps.titulatec.services.document_service import DocumentService
        q = AppointmentService._unscheduled_query(
            db, program_id=program_id, allowed_program_ids=allowed_program_ids)
        if q is None:
            return []
        q = q.filter(~db.query(SurveyReview.id)
                    .filter(SurveyReview.process_id == TitulationProcess.id)
                    .exists())
        candidates = q.order_by(TitulationProcess.created_at).all()
        return [p for p in candidates if DocumentService.initial_docs_all_approved(db, p.id)]

    @staticmethod
    def list_reschedule_processes(db: Session, *,
                                  allowed_program_ids: set | None = None) -> list:
        """Procesos cuya cita quedó en `no_show` y siguen activos.

        Son trabajo pendiente del encargado, pero de otra clase que «Por
        agendar»: aquí el alumno ya tuvo su lugar y no llegó. Se listan aparte
        para que el contador de la cola siga significando una sola cosa.

        El `no_show` tiene que ser el VIGENTE, y el filtro arregla dos cosas a
        la vez: sin él, (a) quien ya fue reagendado tras su ausencia se
        quedaba en este cubo para siempre —y salía a la vez aquí y en la
        agenda, con lo que los cuatro cubos de la cola dejaban de ser
        mutuamente excluyentes—, y (b) dos filas `no_show` del mismo proceso
        lo listaban DOS VECES, porque el join multiplica.
        """
        from itcj2.apps.titulatec.models import ReviewAppointment, TitulationProcess
        if allowed_program_ids is not None and len(allowed_program_ids) == 0:
            return []
        q = (db.query(TitulationProcess)
             .join(ReviewAppointment, ReviewAppointment.process_id == TitulationProcess.id)
             .filter(TitulationProcess.status == "active",
                     ReviewAppointment.is_current.is_(True),
                     ReviewAppointment.status == "no_show"))
        if allowed_program_ids is not None:
            q = q.filter(TitulationProcess.program_id.in_(allowed_program_ids))
        return q.order_by(ReviewAppointment.scheduled_at).all()

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _log(db: Session, process_id: int, actor_id: int, event_type: str, payload: dict | None = None):
        from itcj2.apps.titulatec.models import ProcessEvent
        db.add(ProcessEvent(
            process_id=process_id, actor_id=actor_id,
            event_type=event_type, phase_number=2, payload=payload,
        ))

    _MONTHS_ES = ["", "ene", "feb", "mar", "abr", "may", "jun",
                  "jul", "ago", "sep", "oct", "nov", "dic"]

    @staticmethod
    def _notify_appt(db: Session, process_id: int, ntype: str, title: str,
                     scheduled_at: datetime, location: str | None) -> None:
        """Avisa al alumno (in-app) de un cambio en su cita. Best-effort."""
        from itcj2.apps.titulatec.models import TitulationProcess
        from itcj2.apps.titulatec.services.notify import notify_student

        proc = db.get(TitulationProcess, process_id)
        if not proc:
            return
        when = (f"{scheduled_at.day:02d} {AppointmentService._MONTHS_ES[scheduled_at.month]} "
                f"{scheduled_at.year} · {scheduled_at:%H:%M}")
        body = when + (f" · {location}" if location else "")
        notify_student(db, proc.student_id, type=ntype, title=title, body=body,
                       process_id=process_id, phase_number=2)

    # -------------------------------------------------- acciones del encargado
    @staticmethod
    def create(db: Session, process_id: int, *, window_id: int | None,
               slot_start: time | None, created_by_id: int,
               location: str | None = None, booked_by: str = "officer"):
        """Abre un intento de cita en una franja concreta. Dueña de la transacción.

        Valida, en este orden: que el alumno YA HAYA ENVIADO la encuesta de
        egresados (`SurveyNotSubmitted`, D2 — sirve cualquier estado de
        revisión; GTV puede seguir revisando en paralelo), que haya ventana y
        franja (`MissingSchedule`), que no haya ya una cita ACTIVA
        (`AppointmentConflict`, D4), que el día siga habilitado
        (`DayNotAllowed`), que la hora sea una franja real (`InvalidSlot`) y
        que quede lugar (`SlotFull`). La guarda de la encuesta va PRIMERO y
        aplica a todo `create`: sin ella no hay nada más que validar.

        `booked_by` ∈ {officer, student} es el distintivo «Agendada por el
        alumno» del tablero (D11). Lo pone quien llama, no se adivina del
        actor: el encargado también agenda con el id de otro usuario delante.

        Es el camino de los intentos NUEVOS, incluidos los que siguen a un
        `no_show` (D7), a una `attended` con faltantes (D5) y a una
        `cancelled` (D6). Mover una cita viva es `reschedule`.
        """
        from itcj2.apps.titulatec.models import ReviewWindow
        from itcj2.apps.titulatec.services.appointment_errors import (
            MissingSchedule, SurveyNotSubmitted,
        )
        from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
        from itcj2.apps.titulatec.services.slot_service import SlotService
        from itcj2.apps.titulatec.services.survey_review_service import SurveyReviewService

        if SurveyReviewService.get_for_process(db, process_id) is None:
            raise SurveyNotSubmitted()

        if not window_id or slot_start is None:
            raise MissingSchedule()

        # D4: UNA cita activa a la vez. Antes esto era
        # `assert_transition(previa.status, "scheduled")`, que con el historial
        # ya no aplica: abrir un intento nuevo no es una transición, es una
        # fila nueva. Y la guarda vieja rechazaba de más — dejaba sin salida a
        # la `attended` con faltantes (D5), al `no_show` (D7) y a la
        # `cancelled` (D6), que son justo los casos que esta feature viene a
        # habilitar. Solo lo VIVO bloquea.
        previa = AppointmentService.get_for_process(db, process_id)
        if previa is not None and previa.status in _ESTADOS_ACTIVOS:
            raise AppointmentConflict()

        window = db.get(ReviewWindow, int(window_id))
        if window is None:
            from itcj2.apps.titulatec.services.appointment_errors import InvalidSlot
            raise InvalidSlot("Ese espacio ya no existe.")
        ReviewDayService.assert_allowed(db, window.review_day.cohort_id,
                                        window.review_day.date)

        # `assign` INSERTA una fila nueva (ya vigente, `scheduled`, sin
        # confirmar y con `attempt_no+1`), y cierra la anterior si la había.
        # Por eso ya no hace falta pisarle `status` ni `confirmed_at`: hacerlo
        # sugeriría que la fila puede venir con restos del intento anterior.
        # `rechazar_activa=True`: la guarda de arriba corre fuera de los locks,
        # así que dos `create` concurrentes del mismo proceso la pasarían los
        # dos. La que vale es la de dentro del advisory lock.
        appt = SlotService.assign(db, window_id, slot_start, process_id,
                                  created_by_id, location=location,
                                  rechazar_activa=True)
        appt.booked_by = booked_by
        AppointmentService._log(
            db, process_id, created_by_id, "appointment_scheduled",
            {"scheduled_at": appt.scheduled_at.isoformat(), "location": appt.location,
             "window_id": window.id})
        # Avisa al alumno SALVO que haya sido él quien agendó: acaba de pulsar
        # el botón y notificarle su propio clic es ruido (auto-agendado, §4.1).
        # Es la misma condición EXACTA que `cancel` —actor == alumno— y por la
        # misma razón. Cuando agenda el encargado, el alumno sí recibe su aviso.
        # `int()` en los dos lados NO es adorno: `user["sub"]` es **string**
        # (gotcha 5 del CLAUDE.md raíz), y sin la coerción `"7" != 7` es
        # siempre verdadero — el alumno recibiría aviso de su propio clic y el
        # silencio de esta rama sería mentira.
        from itcj2.apps.titulatec.models import TitulationProcess
        proc = db.get(TitulationProcess, process_id)
        if proc is None or int(created_by_id) != int(proc.student_id):
            AppointmentService._notify_appt(db, process_id, "APPOINTMENT_SCHEDULED",
                                            "Tu cita de cotejo fue agendada",
                                            appt.scheduled_at, appt.location)
        db.commit()
        db.refresh(appt)
        return appt

    @staticmethod
    def reschedule(db: Session, appt, *, window_id: int | None,
                   slot_start: time | None, actor_id: int,
                   location: str | None = None):
        """Mueve al alumno a otra franja. **Devuelve una fila NUEVA.**

        Ya no muta la cita: cierra la que había e inserta el intento
        siguiente, así que la referencia que el llamador traía queda apuntando
        al intento **anterior**, con su hora vieja y su `confirmed_at`. Quien
        necesite la cita resultante tiene que leer el valor de retorno o
        volver a pedir `get_for_process`.

        Qué le pasa a la fila vieja depende de su estado, y son dos cosas
        distintas (§2.2): una cita ACTIVA pasa a `superseded`; un `no_show`
        **conserva su status y su franja** (D7 + D10), solo deja de ser la
        vigente. Esa asimetría vive en `SlotService._open_new_attempt`.

        `_REAGENDABLES` deja fuera `in_progress` (un cotejo empezado se cierra
        con `attended` o `no_show`) y los tres terminales.

        **No toca `change_request`.** Antes hacía `appt.note = note`, así que la
        solicitud del alumno se perdía justo al atenderla; ahora se queda en el
        intento al que pertenecía y la cita nueva nace limpia.
        """
        from itcj2.apps.titulatec.models import ReviewWindow
        from itcj2.apps.titulatec.services.appointment_errors import (
            InvalidSlot, MissingSchedule,
        )
        from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
        from itcj2.apps.titulatec.services.slot_service import SlotService

        if not window_id or slot_start is None:
            raise MissingSchedule()
        if appt.status not in _REAGENDABLES:
            raise InvalidTransition(desde=appt.status, hacia="scheduled")

        window = db.get(ReviewWindow, int(window_id))
        if window is None:
            raise InvalidSlot("Ese espacio ya no existe.")
        ReviewDayService.assert_allowed(db, window.review_day.cohort_id,
                                        window.review_day.date)

        # Igual que en `create`: la fila que vuelve es NUEVA y ya nace
        # `scheduled` y sin confirmar. Reasignar `appt` aquí es deliberado —
        # todo lo que sigue (log, notificación, refresh) habla de la cita
        # nueva, no de la que se acaba de cerrar.
        appt = SlotService.assign(db, window_id, slot_start, appt.process_id,
                                  actor_id, location=location)
        AppointmentService._log(db, appt.process_id, actor_id, "appointment_rescheduled",
                                {"scheduled_at": appt.scheduled_at.isoformat(),
                                 "window_id": window.id})
        AppointmentService._notify_appt(db, appt.process_id, "APPOINTMENT_RESCHEDULED",
                                        "Tu cita de cotejo fue reagendada",
                                        appt.scheduled_at, appt.location)
        db.commit()
        db.refresh(appt)
        return appt

    @staticmethod
    def start(db: Session, appt, actor_id: int):
        """Inicia el cotejo presencial."""
        AppointmentService.assert_transition(appt.status, "in_progress")
        appt.status = "in_progress"
        AppointmentService._log(db, appt.process_id, actor_id, "appointment_in_progress")
        db.commit()
        db.refresh(appt)
        return appt

    @staticmethod
    def mark_attended(db: Session, appt, actor_id: int):
        """Marca 'asistió' (cotejo concluido). NO aprueba la fase (paso aparte).

        Solo desde `in_progress`: llegar aquí desde `scheduled` se saltaría el
        cotejo, y desde `no_show` reescribiría la historia.
        """
        AppointmentService.assert_transition(appt.status, "attended")
        appt.status = "attended"
        AppointmentService._log(db, appt.process_id, actor_id, "appointment_attended")
        db.commit()
        db.refresh(appt)
        return appt

    @staticmethod
    def mark_no_show(db: Session, appt, actor_id: int):
        """El alumno no llegó. Su lugar NO se libera: la franja ya se consumió."""
        AppointmentService.assert_transition(appt.status, "no_show")
        appt.status = "no_show"
        AppointmentService._log(db, appt.process_id, actor_id, "appointment_no_show")
        db.commit()
        db.refresh(appt)
        return appt

    @staticmethod
    def undo_no_show(db: Session, appt, actor_id: int):
        """«Deshacer no se presentó». Devuelve la cita a `in_progress`.

        Existe porque marcar una ausencia es un clic con consecuencias para un
        egresado (le dispara notificación) y hasta ahora no tenía reverso.
        """
        AppointmentService.assert_transition(appt.status, "in_progress")
        appt.status = "in_progress"
        AppointmentService._log(db, appt.process_id, actor_id, "appointment_undo_no_show")
        db.commit()
        db.refresh(appt)
        return appt

    # -------------------------------------------- compartido: alumno y encargado
    @staticmethod
    def cancel(db: Session, appt, actor_id: int, reason: str | None = None):
        """Cancela la cita y libera su franja. Dueña de la transacción.

        D12, y la asimetría deliberada con D10: cancelar **sí** devuelve el
        lugar al pozo, no presentarse **no**. Cancelar a tiempo es un aviso;
        no presentarse ya consumió la franja. Lo implementa
        `SlotService._ESTADOS_QUE_LIBERAN`, donde está `cancelled` y no está
        `no_show`.

        La fila deja de ser la vigente, así que para el resto de la app el
        proceso vuelve a estar «sin cita» y puede agendarse otra (D6).

        Una sola función para los dos actores a propósito: las reglas del
        ALUMNO —la ventana de 2 h (D8) y el tope de cancelaciones (D9)— NO
        viven aquí sino en `SelfBookingService`, que envuelve a ésta (D13). Si
        se colaran a esta capa se le aplicarían también al encargado, que no
        tiene ventana de tiempo.

        **Avisa al alumno solo si la cancelación NO fue suya.** D11 quita la
        notificación AL ENCARGADO por un auto-agendado; no dice callarle al
        alumno, y una cancelación es más disruptiva que una reagenda —que sí
        le avisa—. Quien cancela su propia cita acaba de pulsar el botón, así
        que a ése no se le avisa de su propio clic.
        """
        AppointmentService.assert_transition(appt.status, "cancelled")
        appt.status = "cancelled"
        appt.is_current = False
        appt.cancelled_at = db_now()
        appt.cancelled_by_id = actor_id
        # Sin motivo se queda en NULL en vez de inventar un texto: el contador
        # de D9 mira `cancelled_by_id`, nunca el motivo, y un "Sin motivo"
        # fabricado se leería como algo que el alumno escribió.
        appt.cancel_reason = (reason or "").strip() or None
        AppointmentService._log(
            db, appt.process_id, actor_id, "appointment_cancelled",
            {"reason": appt.cancel_reason,
             "scheduled_at": appt.scheduled_at.isoformat() if appt.scheduled_at else None})

        from itcj2.apps.titulatec.models import TitulationProcess
        proc = db.get(TitulationProcess, appt.process_id)
        # `int()` en los dos lados: `user["sub"]` es string y sin la coerción
        # la comparación es siempre verdadera (gotcha 5), así que el alumno
        # recibiría aviso de su propia cancelación.
        if proc is not None and int(actor_id) != int(proc.student_id):
            AppointmentService._notify_appt(
                db, appt.process_id, "APPOINTMENT_CANCELLED",
                "Tu cita de cotejo fue cancelada",
                appt.scheduled_at, appt.location)
        db.commit()
        db.refresh(appt)
        return appt

    # ----------------------------------------------------- acciones del alumno
    @staticmethod
    def confirm(db: Session, appt, actor_id: int):
        """El alumno confirma asistencia."""
        AppointmentService.assert_transition(appt.status, "confirmed")
        appt.status = "confirmed"
        appt.confirmed_at = db_now()
        AppointmentService._log(db, appt.process_id, actor_id, "appointment_confirmed")
        db.commit()
        db.refresh(appt)
        return appt

    @staticmethod
    def request_change(db: Session, appt, actor_id: int, reason: str | None):
        """El alumno solicita un cambio de cita (el encargado decide y reagenda).

        Columna propia, no un prefijo mágico dentro de `note`: con el prefijo,
        `create` y `reschedule` la pisaban, y una nota operativa que empezara
        con «[CAMBIO] » se leía como solicitud del alumno.
        """
        appt.change_request = (reason or "Sin motivo").strip()
        appt.change_requested_at = db_now()
        AppointmentService._log(db, appt.process_id, actor_id, "appointment_change_requested",
                                {"reason": reason})
        db.commit()
        db.refresh(appt)
        return appt
