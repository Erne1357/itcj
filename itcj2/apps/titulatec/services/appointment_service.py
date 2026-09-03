"""Citas de cotejo de documentos (fase 2, Servicios Escolares).

Una cita por proceso. El encargado de la carrera agenda, reagenda y marca el
cotejo; el alumno confirma o solicita un cambio. Los cambios relevantes escriben
un ``ProcessEvent`` (phase_number=2). El commit vive aquí.

Estados de ``ReviewAppointment.status``::

    scheduled    agendada, pendiente de confirmación del alumno
    confirmed    el alumno confirmó asistencia
    in_progress  el encargado está atendiendo el cotejo
    attended     cotejo concluido (la fase se aprueba aparte)
    no_show      el alumno no se presentó

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

from itcj2.apps.titulatec.services.appointment_errors import InvalidTransition
from itcj2.core.utils.timezone import db_now


class AppointmentService:
    # Matriz de transiciones. `attended` no aparece como origen: es terminal.
    _TRANSICIONES: dict[str, set[str]] = {
        "scheduled":   {"scheduled", "confirmed", "in_progress", "no_show"},
        "confirmed":   {"scheduled", "in_progress", "no_show"},
        "in_progress": {"scheduled", "attended", "no_show"},
        "no_show":     {"scheduled", "in_progress"},
        "attended":    set(),
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
        """Cita más reciente del proceso (o None)."""
        from itcj2.apps.titulatec.models import ReviewAppointment
        return (
            db.query(ReviewAppointment)
            .filter_by(process_id=process_id)
            .order_by(ReviewAppointment.id.desc())
            .first()
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
        )
        if allowed_program_ids is not None:
            q = q.filter(TitulationProcess.program_id.in_(allowed_program_ids))
        return {pid for (pid,) in q.distinct()}

    @staticmethod
    def list_pending_processes(db: Session, *, program_id: int | None = None,
                               allowed_program_ids: set | None = None) -> list:
        """Procesos activos, SIN cita, con los 3 documentos iniciales aprobados.

        Los `no_show` NO entran aquí: conservan su cita y su lugar (decisión del
        usuario, «si no se presentó es que ya pasó»). Viven en su propio cubo,
        `list_reschedule_processes`, para que nadie se pierda sin mezclar dos
        cosas distintas.
        """
        from itcj2.apps.titulatec.models import ReviewAppointment, TitulationProcess
        from itcj2.apps.titulatec.services.document_service import DocumentService
        if allowed_program_ids is not None and len(allowed_program_ids) == 0:
            return []
        with_appt = [pid for (pid,) in db.query(ReviewAppointment.process_id).distinct()]
        q = db.query(TitulationProcess).filter(TitulationProcess.status == "active")
        if with_appt:
            q = q.filter(~TitulationProcess.id.in_(with_appt))
        if allowed_program_ids is not None:
            q = q.filter(TitulationProcess.program_id.in_(allowed_program_ids))
        if program_id:
            q = q.filter(TitulationProcess.program_id == program_id)
        candidates = q.order_by(TitulationProcess.created_at).all()
        return [p for p in candidates if DocumentService.initial_docs_all_approved(db, p.id)]

    @staticmethod
    def list_reschedule_processes(db: Session, *,
                                  allowed_program_ids: set | None = None) -> list:
        """Procesos cuya cita quedó en `no_show` y siguen activos.

        Son trabajo pendiente del encargado, pero de otra clase que «Por
        agendar»: aquí el alumno ya tuvo su lugar y no llegó. Se listan aparte
        para que el contador de la cola siga significando una sola cosa.
        """
        from itcj2.apps.titulatec.models import ReviewAppointment, TitulationProcess
        if allowed_program_ids is not None and len(allowed_program_ids) == 0:
            return []
        q = (db.query(TitulationProcess)
             .join(ReviewAppointment, ReviewAppointment.process_id == TitulationProcess.id)
             .filter(TitulationProcess.status == "active",
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
               location: str | None = None):
        """Agenda la cita en una franja concreta. Dueña de la transacción.

        Valida, en este orden: que haya ventana y franja (`MissingSchedule`),
        que el día siga habilitado (`DayNotAllowed`), que la hora sea una franja
        real (`InvalidSlot`) y que quede lugar (`SlotFull`).
        """
        from itcj2.apps.titulatec.models import ReviewWindow
        from itcj2.apps.titulatec.services.appointment_errors import MissingSchedule
        from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
        from itcj2.apps.titulatec.services.slot_service import SlotService

        if not window_id or slot_start is None:
            raise MissingSchedule()

        # Un proceso tiene una sola cita: si ya la tiene, esto es un movimiento
        # y hay que respetar la matriz. Sin esta guarda, `create` sobre una cita
        # ya `attended` la devolvia a `scheduled` en silencio.
        previa = AppointmentService.get_for_process(db, process_id)
        if previa is not None:
            AppointmentService.assert_transition(previa.status, "scheduled")

        window = db.get(ReviewWindow, int(window_id))
        if window is None:
            from itcj2.apps.titulatec.services.appointment_errors import InvalidSlot
            raise InvalidSlot("Ese espacio ya no existe.")
        ReviewDayService.assert_allowed(db, window.review_day.cohort_id,
                                        window.review_day.date)

        appt = SlotService.assign(db, window_id, slot_start, process_id,
                                  created_by_id, location=location)
        appt.status = "scheduled"
        appt.confirmed_at = None
        AppointmentService._log(
            db, process_id, created_by_id, "appointment_scheduled",
            {"scheduled_at": appt.scheduled_at.isoformat(), "location": appt.location,
             "window_id": window.id})
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
        """Mueve la cita a otra franja. Vuelve a `scheduled`.

        **No toca `change_request`.** Antes hacía `appt.note = note`, así que la
        solicitud del alumno se perdía justo al atenderla.
        """
        from itcj2.apps.titulatec.models import ReviewWindow
        from itcj2.apps.titulatec.services.appointment_errors import (
            InvalidSlot, MissingSchedule,
        )
        from itcj2.apps.titulatec.services.review_day_service import ReviewDayService
        from itcj2.apps.titulatec.services.slot_service import SlotService

        if not window_id or slot_start is None:
            raise MissingSchedule()
        AppointmentService.assert_transition(appt.status, "scheduled")

        window = db.get(ReviewWindow, int(window_id))
        if window is None:
            raise InvalidSlot("Ese espacio ya no existe.")
        ReviewDayService.assert_allowed(db, window.review_day.cohort_id,
                                        window.review_day.date)

        appt = SlotService.assign(db, window_id, slot_start, appt.process_id,
                                  actor_id, location=location)
        appt.status = "scheduled"
        appt.confirmed_at = None
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
