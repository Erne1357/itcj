"""
Servicio de solicitudes para AgendaTec.
Migrado de itcj/apps/agendatec/services/request_service.py (Flask) a SQLAlchemy puro.

Centraliza la lógica de negocio para gestión de solicitudes de estudiantes:
- Validaciones de creación
- Creación de solicitudes de baja y citas
- Cancelación de solicitudes
- Consulta de solicitudes
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from itcj2.apps.agendatec.models.appointment import Appointment
from itcj2.apps.agendatec.models.request import Request
from itcj2.apps.agendatec.models.time_slot import TimeSlot
from itcj2.core.models.academic_period import AcademicPeriod
from itcj2.core.models.program import Program
from itcj2.core.models.program_coordinator import ProgramCoordinator
from itcj2.core.models.user import User
from itcj2.core.services import period_service
from itcj2.core.services.notification_service import NotificationService
from itcj2.core.utils.redis_conn import get_redis
from itcj2.sockets.notifications import push_notification
from itcj2.sockets.requests import (
    broadcast_appointment_created,
    broadcast_drop_created,
    broadcast_request_status_changed,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _async_broadcast(coro):
    """Dispara un coroutine de broadcast sin bloquear el hilo síncrono."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# DATACLASSES PARA RESULTADOS
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ServiceResult:
    """Resultado genérico de operación del servicio."""
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None
    message: Optional[str] = None
    status_code: int = 200


@dataclass
class ValidationResult:
    """Resultado de validación."""
    is_valid: bool
    error: Optional[str] = None
    message: Optional[str] = None
    extra_data: Optional[dict] = None


# ═══════════════════════════════════════════════════════════════════════════════
# SERVICIO DE SOLICITUDES
# ═══════════════════════════════════════════════════════════════════════════════


class RequestService:
    """
    Servicio para gestión de solicitudes de estudiantes.

    Encapsula toda la lógica de negocio relacionada con:
    - Creación de solicitudes de baja (DROP)
    - Creación de solicitudes de cita (APPOINTMENT)
    - Cancelación de solicitudes
    - Validaciones de período, días habilitados, conflictos
    """

    # ───────────────────────────────────────────────────────────────────────────
    # VALIDACIONES
    # ───────────────────────────────────────────────────────────────────────────

    def validate_active_period(self, db: Session) -> ValidationResult:
        """Valida que exista un período académico activo."""
        period = period_service.get_active_period(db)
        if not period:
            return ValidationResult(
                is_valid=False,
                error="no_active_period",
                message="No hay un período académico activo",
            )
        return ValidationResult(is_valid=True, extra_data={"period": period})

    def validate_no_existing_request(
        self, db: Session, student_id: int, period_id: int
    ) -> ValidationResult:
        """Valida que el estudiante no tenga una solicitud activa en el período."""
        existing = (
            db.query(Request)
            .filter(
                Request.student_id == student_id,
                Request.period_id == period_id,
                Request.status != "CANCELED",
            )
            .first()
        )

        if existing:
            period = db.get(AcademicPeriod, period_id)
            period_name = period.name if period else "actual"
            return ValidationResult(
                is_valid=False,
                error="already_has_request_in_period",
                message=f"Ya tienes una solicitud en el período '{period_name}'.",
                extra_data={
                    "existing_request_id": existing.id,
                    "existing_request_status": existing.status,
                },
            )
        return ValidationResult(is_valid=True)

    def validate_slot_for_appointment(
        self, db: Session, slot_id: int, program_id: int, period_id: int
    ) -> ValidationResult:
        """Valida que un slot esté disponible para una cita."""
        slot = db.get(TimeSlot, slot_id)
        if not slot:
            return ValidationResult(
                is_valid=False,
                error="slot_not_found",
                message="El horario no existe",
            )

        if slot.is_booked:
            return ValidationResult(
                is_valid=False,
                error="slot_unavailable",
                message="El horario ya está ocupado",
            )

        enabled_days = set(period_service.get_enabled_days(db, period_id))
        if slot.day not in enabled_days:
            return ValidationResult(
                is_valid=False,
                error="day_not_enabled",
                message="El día seleccionado no está habilitado para este período",
                extra_data={"enabled_days": [d.isoformat() for d in sorted(enabled_days)]},
            )

        now = datetime.now()
        slot_datetime = datetime.combine(slot.day, slot.start_time)
        if now > slot_datetime:
            return ValidationResult(
                is_valid=False,
                error="slot_time_passed",
                message="El horario ya pasó",
            )

        link = (
            db.query(ProgramCoordinator)
            .filter(
                ProgramCoordinator.program_id == program_id,
                ProgramCoordinator.coordinator_id == slot.coordinator_id,
            )
            .first()
        )
        if not link:
            return ValidationResult(
                is_valid=False,
                error="slot_not_for_program",
                message="El coordinador no está asignado a tu programa",
            )

        return ValidationResult(is_valid=True, extra_data={"slot": slot})

    def validate_can_cancel(self, db: Session, request: Request) -> ValidationResult:
        """Valida que una solicitud pueda ser cancelada."""
        if request.status != "PENDING":
            return ValidationResult(
                is_valid=False,
                error="not_pending",
                message="Solo se pueden cancelar solicitudes en estado PENDING",
            )

        period = db.get(AcademicPeriod, request.period_id)
        if period and period.status != "ACTIVE":
            return ValidationResult(
                is_valid=False,
                error="period_closed",
                message=f"No se puede cancelar porque el período '{period.name}' ya cerró.",
            )

        if request.type == "APPOINTMENT":
            ap = (
                db.query(Appointment)
                .filter(Appointment.request_id == request.id)
                .first()
            )
            if ap:
                slot = db.get(TimeSlot, ap.slot_id)
                if slot:
                    now = datetime.now()
                    slot_datetime = datetime.combine(slot.day, slot.start_time)
                    if now >= slot_datetime:
                        return ValidationResult(
                            is_valid=False,
                            error="appointment_time_passed",
                            message="No se puede cancelar porque la cita ya pasó.",
                        )

        return ValidationResult(is_valid=True)

    # ───────────────────────────────────────────────────────────────────────────
    # CREACIÓN DE SOLICITUDES
    # ───────────────────────────────────────────────────────────────────────────

    def create_drop_request(
        self,
        db: Session,
        student: User,
        program_id: int,
        description: Optional[str] = None,
    ) -> ServiceResult:
        """Crea una solicitud de baja."""
        logger.info("Iniciando creación de solicitud de baja", extra={
            "student_id": student.id, "program_id": program_id
        })

        period_validation = self.validate_active_period(db)
        if not period_validation.is_valid:
            return ServiceResult(
                success=False,
                error=period_validation.error,
                message=period_validation.message,
                status_code=503,
            )
        period = period_validation.extra_data["period"]

        existing_validation = self.validate_no_existing_request(db, student.id, period.id)
        if not existing_validation.is_valid:
            return ServiceResult(
                success=False,
                error=existing_validation.error,
                message=existing_validation.message,
                data=existing_validation.extra_data,
                status_code=409,
            )

        request_obj = Request(
            student_id=student.id,
            program_id=program_id,
            period_id=period.id,
            description=description,
            type="DROP",
            status="PENDING",
        )
        db.add(request_obj)
        db.commit()

        logger.info("Solicitud de baja creada", extra={
            "request_id": request_obj.id, "period_id": period.id
        })

        self._notify_drop_created(db, request_obj, student)
        self._notify_student_drop_created(db, request_obj, student)

        return ServiceResult(
            success=True,
            data={"request_id": request_obj.id},
            status_code=200,
        )

    def create_appointment_request(
        self,
        db: Session,
        student: User,
        program_id: int,
        slot_id: int,
        description: Optional[str] = None,
    ) -> ServiceResult:
        """Crea una solicitud de cita."""
        logger.info("Iniciando creación de solicitud de cita", extra={
            "student_id": student.id, "program_id": program_id, "slot_id": slot_id
        })

        period_validation = self.validate_active_period(db)
        if not period_validation.is_valid:
            return ServiceResult(
                success=False,
                error=period_validation.error,
                message=period_validation.message,
                status_code=503,
            )
        period = period_validation.extra_data["period"]

        existing_validation = self.validate_no_existing_request(db, student.id, period.id)
        if not existing_validation.is_valid:
            return ServiceResult(
                success=False,
                error=existing_validation.error,
                message=existing_validation.message,
                data=existing_validation.extra_data,
                status_code=409,
            )

        prog = db.get(Program, program_id)
        if not prog:
            return ServiceResult(
                success=False,
                error="program_not_found",
                message="Programa no encontrado",
                status_code=404,
            )

        slot_validation = self.validate_slot_for_appointment(db, slot_id, program_id, period.id)
        if not slot_validation.is_valid:
            return ServiceResult(
                success=False,
                error=slot_validation.error,
                message=slot_validation.message,
                data=slot_validation.extra_data,
                status_code=400 if slot_validation.error != "slot_unavailable" else 409,
            )
        slot = slot_validation.extra_data["slot"]

        try:
            updated = (
                db.query(TimeSlot)
                .filter(TimeSlot.id == slot_id, TimeSlot.is_booked == False)
                .update({TimeSlot.is_booked: True}, synchronize_session=False)
            )
            if updated != 1:
                logger.warning("Conflicto al reservar slot", extra={"slot_id": slot_id})
                db.rollback()
                return ServiceResult(
                    success=False,
                    error="slot_conflict",
                    message="El horario fue tomado por otro estudiante",
                    status_code=409,
                )

            request_obj = Request(
                student_id=student.id,
                program_id=program_id,
                period_id=period.id,
                description=description,
                type="APPOINTMENT",
                status="PENDING",
            )
            db.add(request_obj)
            db.flush()

            appointment = Appointment(
                request_id=request_obj.id,
                student_id=student.id,
                program_id=program_id,
                coordinator_id=slot.coordinator_id,
                slot_id=slot_id,
                status="SCHEDULED",
            )
            db.add(appointment)
            db.commit()

            logger.info("Solicitud de cita creada", extra={
                "request_id": request_obj.id,
                "appointment_id": appointment.id,
                "slot_day": str(slot.day),
                "coordinator_id": slot.coordinator_id,
            })

            self._notify_slot_booked(slot)
            self._notify_appointment_created(request_obj, appointment, slot)
            self._notify_student_appointment_created(db, request_obj, appointment, slot, student)

            return ServiceResult(
                success=True,
                data={"request_id": request_obj.id, "appointment_id": appointment.id},
                status_code=200,
            )

        except IntegrityError as e:
            logger.exception("Error de integridad al crear cita", extra={"error": str(e)})
            db.rollback()
            return ServiceResult(
                success=False,
                error="conflict",
                message="Error de integridad al crear la cita",
                status_code=409,
            )

    # ───────────────────────────────────────────────────────────────────────────
    # CANCELACIÓN
    # ───────────────────────────────────────────────────────────────────────────

    def cancel_request(self, db: Session, request: Request, student: User) -> ServiceResult:
        """Cancela una solicitud del estudiante."""
        logger.info("Iniciando cancelación de solicitud", extra={
            "student_id": student.id, "request_id": request.id, "type": request.type
        })

        validation = self.validate_can_cancel(db, request)
        if not validation.is_valid:
            status = 400 if validation.error == "not_pending" else 403
            return ServiceResult(
                success=False,
                error=validation.error,
                message=validation.message,
                status_code=status,
            )

        slot = None
        appointment = None

        if request.type == "APPOINTMENT":
            appointment = (
                db.query(Appointment)
                .filter(Appointment.request_id == request.id)
                .first()
            )
            if appointment:
                slot = db.get(TimeSlot, appointment.slot_id)
                if slot and slot.is_booked:
                    slot.is_booked = False
                appointment.status = "CANCELED"

        request.status = "CANCELED"
        db.commit()

        logger.info("Solicitud cancelada", extra={"slot_released": slot.id if slot else None})

        if request.type == "APPOINTMENT" and slot:
            self._notify_slot_released(slot, appointment)
        self._notify_request_canceled(db, request, appointment)
        self._notify_student_canceled(db, request, student)

        return ServiceResult(success=True, data={"ok": True}, status_code=200)

    # ───────────────────────────────────────────────────────────────────────────
    # CONSULTAS
    # ───────────────────────────────────────────────────────────────────────────

    def get_student_requests(self, db: Session, student: User) -> dict:
        """Obtiene las solicitudes de un estudiante."""
        from sqlalchemy import and_, or_

        active_period = period_service.get_active_period(db)
        active_period_info = None

        if active_period:
            config = period_service.get_agendatec_config(db, active_period.id)
            active_period_info = {
                "id": active_period.id,
                "name": active_period.name,
                "status": active_period.status,
                "end_date": active_period.end_date.isoformat() if active_period.end_date else None,
            }
            if config and config.student_admission_deadline:
                active_period_info["student_admission_deadline"] = (
                    config.student_admission_deadline.isoformat()
                )

        active = None
        if active_period:
            active = (
                db.query(Request)
                .filter(
                    Request.student_id == student.id,
                    Request.period_id == active_period.id,
                    Request.status == "PENDING",
                )
                .order_by(Request.created_at.desc())
                .first()
            )

        history_query = db.query(Request).filter(Request.student_id == student.id)
        if active_period:
            history_query = history_query.filter(
                or_(
                    Request.status != "PENDING",
                    and_(Request.status == "PENDING", Request.period_id != active_period.id),
                )
            )
        history = history_query.order_by(Request.created_at.desc()).all()

        periods_dict = self._build_periods_dict(db, active, history, active_period)

        return {
            "active_period": active_period_info,
            "active": self._request_to_dict(db, active, periods_dict) if active else None,
            "history": [self._request_to_dict(db, r, periods_dict) for r in history],
            "periods": periods_dict,
        }

    # ───────────────────────────────────────────────────────────────────────────
    # MÉTODOS PRIVADOS - NOTIFICACIONES
    # ───────────────────────────────────────────────────────────────────────────

    def _notify_drop_created(self, db: Session, request: Request, student: User) -> None:
        """Notifica a coordinadores sobre nueva solicitud de baja."""
        try:
            coord_ids = [
                row[0]
                for row in db.query(ProgramCoordinator.coordinator_id)
                .filter_by(program_id=request.program_id)
                .all()
            ]
            payload = {
                "request_id": request.id,
                "student_id": student.id,
                "program_id": request.program_id,
                "status": request.status,
            }
            for cid in coord_ids:
                _async_broadcast(broadcast_drop_created(cid, payload))
        except Exception:
            logger.exception("Failed to broadcast drop_created")

    def _notify_student_drop_created(self, db: Session, request: Request, student: User) -> None:
        """Notifica al estudiante que su solicitud de baja fue creada."""
        try:
            n = NotificationService.create(
                db=db,
                user_id=student.id,
                app_name="agendatec",
                type="DROP_CREATED",
                title="Solicitud de baja creada",
                body="Tu solicitud de baja fue registrada.",
                data={"request_id": request.id},
                source_request_id=request.id,
                program_id=request.program_id,
            )
            db.commit()
            _async_broadcast(push_notification(student.id, n.to_dict()))
        except Exception:
            logger.exception("Failed to create/push DROP notification")

    def _notify_slot_booked(self, slot: TimeSlot) -> None:
        """Emite evento de slot reservado."""
        try:
            from itcj2.sockets.server import sio
            slot_day = str(slot.day)
            room = f"day:{slot_day}"
            payload = {
                "slot_id": slot.id,
                "day": slot_day,
                "start_time": slot.start_time.strftime("%H:%M"),
                "end_time": slot.end_time.strftime("%H:%M"),
            }
            _async_broadcast(sio.emit("slot_booked", payload, to=room, namespace="/slots"))
            redis_cli = get_redis()
            redis_cli.delete(f"slot:{slot.id}:hold")
        except Exception:
            logger.exception("Failed to broadcast slot_booked")

    def _notify_appointment_created(
        self, request: Request, appointment: Appointment, slot: TimeSlot
    ) -> None:
        """Notifica al coordinador sobre nueva cita."""
        try:
            day_str = str(slot.day)
            payload = {
                "request_id": request.id,
                "student_id": request.student_id,
                "program_id": appointment.program_id,
                "slot_day": day_str,
                "slot_start": slot.start_time.strftime("%H:%M"),
                "slot_end": slot.end_time.strftime("%H:%M"),
                "status": request.status,
            }
            _async_broadcast(
                broadcast_appointment_created(appointment.coordinator_id, day_str, payload)
            )
        except Exception:
            logger.exception("Failed to broadcast appointment_created")

    def _notify_student_appointment_created(
        self,
        db: Session,
        request: Request,
        appointment: Appointment,
        slot: TimeSlot,
        student: User,
    ) -> None:
        """Notifica al estudiante que su cita fue creada."""
        try:
            slot_day = str(slot.day)
            n = NotificationService.create(
                db=db,
                user_id=student.id,
                app_name="agendatec",
                type="APPOINTMENT_CREATED",
                title="Cita agendada",
                body=f"{slot_day} {slot.start_time.strftime('%H:%M')}–{slot.end_time.strftime('%H:%M')}",
                data={"request_id": request.id, "appointment_id": appointment.id, "day": slot_day},
                source_request_id=request.id,
                source_appointment_id=appointment.id,
                program_id=appointment.program_id,
            )
            db.commit()
            _async_broadcast(push_notification(student.id, n.to_dict()))
        except Exception:
            logger.exception("Failed to create/push APPOINTMENT notification")

    def _notify_slot_released(self, slot: TimeSlot, appointment: Appointment) -> None:
        """Emite evento de slot liberado."""
        try:
            from itcj2.sockets.server import sio
            slot_day = str(slot.day)
            room = f"day:{slot_day}"
            payload = {
                "slot_id": appointment.slot_id,
                "day": slot_day,
                "start_time": slot.start_time.strftime("%H:%M"),
                "end_time": slot.end_time.strftime("%H:%M"),
            }
            _async_broadcast(sio.emit("slot_released", payload, to=room, namespace="/slots"))
            redis_cli = get_redis()
            redis_cli.delete(f"slot:{appointment.slot_id}:hold")
        except Exception:
            logger.exception("Failed to broadcast slot_released")

    def _notify_request_canceled(
        self, db: Session, request: Request, appointment: Optional[Appointment]
    ) -> None:
        """Notifica a coordinadores sobre cancelación."""
        try:
            if request.type == "APPOINTMENT" and appointment:
                slot = db.get(TimeSlot, appointment.slot_id)
                day_str = str(slot.day) if slot else None
                payload = {
                    "type": "APPOINTMENT",
                    "request_id": request.id,
                    "new_status": request.status,
                    "day": day_str,
                    "program_id": request.program_id,
                }
                _async_broadcast(
                    broadcast_request_status_changed(appointment.coordinator_id, payload)
                )
            else:
                coord_ids = [
                    row[0]
                    for row in db.query(ProgramCoordinator.coordinator_id)
                    .filter_by(program_id=request.program_id)
                    .all()
                ]
                payload = {
                    "type": "DROP",
                    "request_id": request.id,
                    "new_status": request.status,
                    "day": None,
                }
                for cid in coord_ids:
                    _async_broadcast(broadcast_request_status_changed(cid, payload))
        except Exception:
            logger.exception("Failed to broadcast request_status_changed")

    def _notify_student_canceled(self, db: Session, request: Request, student: User) -> None:
        """Notifica al estudiante sobre la cancelación."""
        try:
            n = NotificationService.create(
                db=db,
                user_id=student.id,
                app_name="agendatec",
                type="APPOINTMENT_CANCELED" if request.type == "APPOINTMENT" else "REQUEST_STATUS_CHANGED",
                title="Solicitud cancelada",
                body="Has cancelado tu solicitud.",
                data={"request_id": request.id},
                source_request_id=request.id,
                program_id=request.program_id,
            )
            db.commit()
            _async_broadcast(push_notification(student.id, n.to_dict()))
        except Exception:
            logger.exception("Failed to create/push CANCEL notification")

    # ───────────────────────────────────────────────────────────────────────────
    # MÉTODOS PRIVADOS - UTILIDADES
    # ───────────────────────────────────────────────────────────────────────────

    def _build_periods_dict(
        self,
        db: Session,
        active: Optional[Request],
        history: list[Request],
        active_period: Optional[AcademicPeriod],
    ) -> dict:
        """Construye diccionario de períodos para las solicitudes."""
        period_ids = set()
        if active and active.period_id:
            period_ids.add(active.period_id)
        for h in history:
            if h.period_id:
                period_ids.add(h.period_id)

        periods_dict = {}

        if active_period:
            periods_dict[active_period.id] = {
                "id": active_period.id,
                "name": active_period.name,
                "status": active_period.status,
            }

        for pid in period_ids:
            if pid not in periods_dict:
                p = db.get(AcademicPeriod, pid)
                if p:
                    periods_dict[pid] = {
                        "id": p.id,
                        "name": p.name,
                        "status": p.status,
                    }

        return periods_dict

    def _request_to_dict(self, db: Session, r: Request, periods_dict: dict) -> dict:
        """Convierte una Request a diccionario."""
        item = {
            "id": r.id,
            "type": r.type,
            "description": r.description,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
            "comment": r.coordinator_comment,
            "period_id": r.period_id,
            "period": periods_dict.get(r.period_id) if r.period_id else None,
        }
        if r.type == "APPOINTMENT":
            ap = db.query(Appointment).filter(Appointment.request_id == r.id).first()
            if ap:
                sl = db.get(TimeSlot, ap.slot_id)
                if sl:
                    item["appointment"] = {
                        "id": ap.id,
                        "program_id": ap.program_id,
                        "coordinator_id": ap.coordinator_id,
                        "slot": {
                            "id": sl.id,
                            "day": sl.day.isoformat(),
                            "start_time": sl.start_time.isoformat(),
                            "end_time": sl.end_time.isoformat(),
                            "is_booked": sl.is_booked,
                        },
                        "status": ap.status,
                    }
        return item


# ═══════════════════════════════════════════════════════════════════════════════
# INSTANCIA SINGLETON
# ═══════════════════════════════════════════════════════════════════════════════


def get_request_service() -> RequestService:
    """Factory function para obtener instancia del servicio."""
    return RequestService()
