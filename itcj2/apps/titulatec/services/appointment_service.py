"""Citas de cotejo de documentos (fase 2, Servicios Escolares).

Una cita por proceso (la última gana). El encargado de la carrera agenda/edita/
reagenda y marca el cotejo; el alumno confirma o solicita un cambio. Los cambios
relevantes escriben un ``ProcessEvent`` (phase_number=2). Commit en el service.

Estados de ``ReviewAppointment.status``:
    scheduled    → agendada, pendiente de confirmación del alumno
    confirmed    → alumno confirmó asistencia
    in_progress  → encargado atendiendo (cotejo presencial en curso)
    attended     → cotejo concluido (la fase se aprueba aparte)
    no_show      → el alumno no se presentó

La solicitud de cambio del alumno se persiste en ``note`` con un prefijo marcador
(no hay columna dedicada) y se limpia al reagendar/editar.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

CHANGE_REQUEST_PREFIX = "[CAMBIO] "


class AppointmentService:
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
                          allowed_program_ids: set | None = None) -> list:
        """Citas de la agenda, ordenadas por fecha. Filtros opcionales.

        allowed_program_ids: None = sin restricción de carrera; set vacío = devuelve [].
        """
        from itcj2.apps.titulatec.models import ReviewAppointment, TitulationProcess
        if allowed_program_ids is not None and len(allowed_program_ids) == 0:
            return []
        q = (
            db.query(ReviewAppointment)
            .join(TitulationProcess, ReviewAppointment.process_id == TitulationProcess.id)
        )
        if allowed_program_ids is not None:
            q = q.filter(TitulationProcess.program_id.in_(allowed_program_ids))
        if program_id:
            q = q.filter(TitulationProcess.program_id == program_id)
        if status:
            q = q.filter(ReviewAppointment.status == status)
        if owner_id:
            q = q.filter(ReviewAppointment.created_by_id == owner_id)
        return q.order_by(ReviewAppointment.scheduled_at).all()

    @staticmethod
    def list_for_day(db: Session, day, *, allowed_program_ids: set | None = None) -> list:
        """Citas cuyo scheduled_at cae en el día `day` (date), ordenadas por hora.

        allowed_program_ids: None = sin restricción; set vacío = devuelve [].
        """
        from datetime import datetime, time, timedelta
        from itcj2.apps.titulatec.models import ReviewAppointment, TitulationProcess
        if allowed_program_ids is not None and len(allowed_program_ids) == 0:
            return []
        start = datetime.combine(day, time.min)
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
    def list_pending_processes(db: Session, *, program_id: int | None = None,
                               allowed_program_ids: set | None = None) -> list:
        """Procesos en fase 2 (activos) que aún no tienen cita agendada.

        allowed_program_ids: None = sin restricción de carrera; set vacío = devuelve [].
        """
        from itcj2.apps.titulatec.models import ReviewAppointment, TitulationProcess
        if allowed_program_ids is not None and len(allowed_program_ids) == 0:
            return []
        with_appt = [pid for (pid,) in db.query(ReviewAppointment.process_id).distinct()]
        q = db.query(TitulationProcess).filter(
            TitulationProcess.current_phase == 2,
            TitulationProcess.status == "active",
        )
        if with_appt:
            q = q.filter(~TitulationProcess.id.in_(with_appt))
        if allowed_program_ids is not None:
            q = q.filter(TitulationProcess.program_id.in_(allowed_program_ids))
        if program_id:
            q = q.filter(TitulationProcess.program_id == program_id)
        return q.order_by(TitulationProcess.created_at).all()

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

    @staticmethod
    def has_change_request(appt) -> bool:
        return bool(appt and appt.note and appt.note.startswith(CHANGE_REQUEST_PREFIX))

    @staticmethod
    def change_request_text(appt) -> str | None:
        if AppointmentService.has_change_request(appt):
            return appt.note[len(CHANGE_REQUEST_PREFIX):].strip() or "Sin motivo"
        return None

    # -------------------------------------------------- acciones del encargado
    @staticmethod
    def create(db: Session, process_id: int, *, scheduled_at: datetime,
               location: str | None, created_by_id: int, note: str | None = None):
        """Agenda la cita. Si ya existía una, la reescribe (una cita por proceso)."""
        from itcj2.apps.titulatec.models import ReviewAppointment
        appt = AppointmentService.get_for_process(db, process_id)
        if appt:
            appt.scheduled_at = scheduled_at
            appt.location = location
            appt.note = note
            appt.status = "scheduled"
            appt.confirmed_at = None
        else:
            appt = ReviewAppointment(
                process_id=process_id, scheduled_at=scheduled_at, location=location,
                note=note, status="scheduled", created_by_id=created_by_id,
            )
            db.add(appt)
        AppointmentService._log(db, process_id, created_by_id, "appointment_scheduled",
                                {"scheduled_at": scheduled_at.isoformat(), "location": location})
        AppointmentService._notify_appt(db, process_id, "APPOINTMENT_SCHEDULED",
                                        "Tu cita de cotejo fue agendada", scheduled_at, location)
        db.commit()
        db.refresh(appt)
        return appt

    @staticmethod
    def reschedule(db: Session, appt, *, scheduled_at: datetime, location: str | None,
                   actor_id: int, note: str | None = None):
        """Reagenda (libre). Vuelve a 'scheduled' y limpia la solicitud de cambio."""
        appt.scheduled_at = scheduled_at
        appt.location = location
        appt.status = "scheduled"
        appt.confirmed_at = None
        appt.note = note
        AppointmentService._log(db, appt.process_id, actor_id, "appointment_rescheduled",
                                {"scheduled_at": scheduled_at.isoformat()})
        AppointmentService._notify_appt(db, appt.process_id, "APPOINTMENT_RESCHEDULED",
                                        "Tu cita de cotejo fue reagendada", scheduled_at, location)
        db.commit()
        db.refresh(appt)
        return appt

    @staticmethod
    def start(db: Session, appt, actor_id: int):
        """Marca la cita como 'en proceso' (encargado atendiendo el cotejo)."""
        appt.status = "in_progress"
        AppointmentService._log(db, appt.process_id, actor_id, "appointment_in_progress")
        db.commit()
        db.refresh(appt)
        return appt

    @staticmethod
    def mark_attended(db: Session, appt, actor_id: int):
        """Marca 'asistió' (cotejo concluido). NO aprueba la fase (paso aparte)."""
        appt.status = "attended"
        AppointmentService._log(db, appt.process_id, actor_id, "appointment_attended")
        db.commit()
        db.refresh(appt)
        return appt

    @staticmethod
    def mark_no_show(db: Session, appt, actor_id: int):
        appt.status = "no_show"
        AppointmentService._log(db, appt.process_id, actor_id, "appointment_no_show")
        db.commit()
        db.refresh(appt)
        return appt

    # ----------------------------------------------------- acciones del alumno
    @staticmethod
    def confirm(db: Session, appt, actor_id: int):
        """El alumno confirma asistencia."""
        appt.status = "confirmed"
        appt.confirmed_at = datetime.utcnow()
        AppointmentService._log(db, appt.process_id, actor_id, "appointment_confirmed")
        db.commit()
        db.refresh(appt)
        return appt

    @staticmethod
    def request_change(db: Session, appt, actor_id: int, reason: str | None):
        """El alumno solicita un cambio de cita (el encargado decide y reagenda)."""
        appt.note = CHANGE_REQUEST_PREFIX + (reason or "Sin motivo").strip()
        AppointmentService._log(db, appt.process_id, actor_id, "appointment_change_requested",
                                {"reason": reason})
        db.commit()
        db.refresh(appt)
        return appt
