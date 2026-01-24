# services/request_service.py
"""
Servicio de solicitudes para AgendaTec.

Este módulo centraliza la lógica de negocio para gestión de solicitudes de estudiantes:
- Validaciones de creación
- Creación de solicitudes de baja y citas
- Cancelación de solicitudes
- Consulta de solicitudes
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from flask import current_app
from sqlalchemy.exc import IntegrityError

from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.appointment import Appointment
from itcj.apps.agendatec.models.request import Request
from itcj.apps.agendatec.models.time_slot import TimeSlot
from itcj.apps.agendatec.utils.logging import get_logger
from itcj.core.models.academic_period import AcademicPeriod
from itcj.core.models.program import Program
from itcj.core.models.program_coordinator import ProgramCoordinator
from itcj.core.models.user import User
from itcj.core.services import period_service
from itcj.core.sockets.notifications import push_notification
from itcj.core.sockets.requests import (
    broadcast_appointment_created,
    broadcast_drop_created,
    broadcast_request_status_changed,
)
from itcj.core.utils.notify import create_notification
from itcj.core.utils.redis_conn import get_redis

if TYPE_CHECKING:
    from flask_socketio import SocketIO


# Logger estructurado para el servicio
_log = get_logger(__name__)


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

    def __init__(self, socketio: Optional["SocketIO"] = None):
        """
        Inicializa el servicio.
        
        Args:
            socketio: Instancia de SocketIO para emisión de eventos en tiempo real.
                     Si no se provee, se intentará obtener de la app actual.
        """
        self._socketio = socketio
        self._log = _log.bind(service="RequestService")

    @property
    def socketio(self) -> Optional["SocketIO"]:
        """Obtiene la instancia de SocketIO."""
        if self._socketio:
            return self._socketio
        return current_app.extensions.get("socketio")

    # ───────────────────────────────────────────────────────────────────────────
    # VALIDACIONES
    # ───────────────────────────────────────────────────────────────────────────

    def validate_active_period(self) -> ValidationResult:
        """
        Valida que exista un período académico activo.
        
        Returns:
            ValidationResult con is_valid=True y el período en extra_data si existe,
            o is_valid=False con error si no hay período activo.
        """
        period = period_service.get_active_period()
        if not period:
            return ValidationResult(
                is_valid=False,
                error="no_active_period",
                message="No hay un período académico activo"
            )
        return ValidationResult(is_valid=True, extra_data={"period": period})

    def validate_no_existing_request(
        self, student_id: int, period_id: int
    ) -> ValidationResult:
        """
        Valida que el estudiante no tenga una solicitud activa en el período.
        
        Args:
            student_id: ID del estudiante.
            period_id: ID del período académico.
            
        Returns:
            ValidationResult indicando si puede crear una nueva solicitud.
        """
        existing = (
            db.session.query(Request)
            .filter(
                Request.student_id == student_id,
                Request.period_id == period_id,
                Request.status != "CANCELED",
            )
            .first()
        )

        if existing:
            period = db.session.query(AcademicPeriod).get(period_id)
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
        self, slot_id: int, program_id: int, period_id: int
    ) -> ValidationResult:
        """
        Valida que un slot esté disponible para una cita.
        
        Args:
            slot_id: ID del slot de tiempo.
            program_id: ID del programa académico.
            period_id: ID del período académico.
            
        Returns:
            ValidationResult con el slot en extra_data si es válido.
        """
        slot = db.session.query(TimeSlot).get(slot_id)
        if not slot:
            return ValidationResult(
                is_valid=False,
                error="slot_not_found",
                message="El horario no existe"
            )

        if slot.is_booked:
            return ValidationResult(
                is_valid=False,
                error="slot_unavailable",
                message="El horario ya está ocupado"
            )

        # Validar que el día esté habilitado
        enabled_days = set(period_service.get_enabled_days(period_id))
        if slot.day not in enabled_days:
            return ValidationResult(
                is_valid=False,
                error="day_not_enabled",
                message="El día seleccionado no está habilitado para este período",
                extra_data={"enabled_days": [d.isoformat() for d in sorted(enabled_days)]},
            )

        # Validar que el slot no haya pasado
        now = datetime.now()
        slot_datetime = datetime.combine(slot.day, slot.start_time)
        if now > slot_datetime:
            return ValidationResult(
                is_valid=False,
                error="slot_time_passed",
                message="El horario ya pasó"
            )

        # Validar que el coordinador esté vinculado al programa
        link = (
            db.session.query(ProgramCoordinator)
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
                message="El coordinador no está asignado a tu programa"
            )

        return ValidationResult(is_valid=True, extra_data={"slot": slot})

    def validate_can_cancel(self, request: Request) -> ValidationResult:
        """
        Valida que una solicitud pueda ser cancelada.
        
        Args:
            request: La solicitud a validar.
            
        Returns:
            ValidationResult indicando si se puede cancelar.
        """
        if request.status != "PENDING":
            return ValidationResult(
                is_valid=False,
                error="not_pending",
                message="Solo se pueden cancelar solicitudes en estado PENDING"
            )

        # Verificar que el período esté activo
        period = db.session.query(AcademicPeriod).get(request.period_id)
        if period and period.status != "ACTIVE":
            return ValidationResult(
                is_valid=False,
                error="period_closed",
                message=f"No se puede cancelar porque el período '{period.name}' ya cerró."
            )

        # Si es APPOINTMENT, verificar que la cita no haya pasado
        if request.type == "APPOINTMENT":
            ap = (
                db.session.query(Appointment)
                .filter(Appointment.request_id == request.id)
                .first()
            )
            if ap:
                slot = db.session.query(TimeSlot).get(ap.slot_id)
                if slot:
                    now = datetime.now()
                    slot_datetime = datetime.combine(slot.day, slot.start_time)
                    if now >= slot_datetime:
                        return ValidationResult(
                            is_valid=False,
                            error="appointment_time_passed",
                            message="No se puede cancelar porque la cita ya pasó."
                        )

        return ValidationResult(is_valid=True)

    # ───────────────────────────────────────────────────────────────────────────
    # CREACIÓN DE SOLICITUDES
    # ───────────────────────────────────────────────────────────────────────────

    def create_drop_request(
        self,
        student: User,
        program_id: int,
        description: Optional[str] = None,
    ) -> ServiceResult:
        """
        Crea una solicitud de baja.
        
        Args:
            student: Usuario estudiante que crea la solicitud.
            program_id: ID del programa académico.
            description: Descripción o motivo de la baja.
            
        Returns:
            ServiceResult con request_id si es exitoso.
        """
        log = self._log.bind(
            operation="create_drop_request",
            student_id=student.id,
            program_id=program_id,
        )
        log.info("Iniciando creación de solicitud de baja")

        # Validar período activo
        period_validation = self.validate_active_period()
        if not period_validation.is_valid:
            log.warning("Sin período activo", extra_data={"error": period_validation.error})
            return ServiceResult(
                success=False,
                error=period_validation.error,
                message=period_validation.message,
                status_code=503,
            )
        period = period_validation.extra_data["period"]

        # Validar que no tenga solicitud activa
        existing_validation = self.validate_no_existing_request(student.id, period.id)
        if not existing_validation.is_valid:
            log.warning("Estudiante ya tiene solicitud activa", extra_data={
                "period_id": period.id,
                "existing_request_id": existing_validation.extra_data.get("existing_request_id"),
            })
            return ServiceResult(
                success=False,
                error=existing_validation.error,
                message=existing_validation.message,
                data=existing_validation.extra_data,
                status_code=409,
            )

        # Crear la solicitud
        request_obj = Request(
            student_id=student.id,
            program_id=program_id,
            period_id=period.id,
            description=description,
            type="DROP",
            status="PENDING",
        )
        db.session.add(request_obj)
        db.session.commit()

        log.info("Solicitud de baja creada exitosamente", extra_data={
            "request_id": request_obj.id,
            "period_id": period.id,
        })

        # Notificar a coordinadores
        self._notify_drop_created(request_obj, student)

        # Notificar al alumno
        self._notify_student_drop_created(request_obj, student)

        return ServiceResult(
            success=True,
            data={"request_id": request_obj.id},
            status_code=200,
        )

    def create_appointment_request(
        self,
        student: User,
        program_id: int,
        slot_id: int,
        description: Optional[str] = None,
    ) -> ServiceResult:
        """
        Crea una solicitud de cita.
        
        Args:
            student: Usuario estudiante que crea la solicitud.
            program_id: ID del programa académico.
            slot_id: ID del slot de tiempo.
            description: Descripción o motivo de la cita.
            
        Returns:
            ServiceResult con request_id y appointment_id si es exitoso.
        """
        log = self._log.bind(
            operation="create_appointment_request",
            student_id=student.id,
            program_id=program_id,
            slot_id=slot_id,
        )
        log.info("Iniciando creación de solicitud de cita")

        # Validar período activo
        period_validation = self.validate_active_period()
        if not period_validation.is_valid:
            log.warning("Sin período activo", extra_data={"error": period_validation.error})
            return ServiceResult(
                success=False,
                error=period_validation.error,
                message=period_validation.message,
                status_code=503,
            )
        period = period_validation.extra_data["period"]

        # Validar que no tenga solicitud activa
        existing_validation = self.validate_no_existing_request(student.id, period.id)
        if not existing_validation.is_valid:
            log.warning("Estudiante ya tiene solicitud activa", extra_data={
                "period_id": period.id,
                "existing_request_id": existing_validation.extra_data.get("existing_request_id"),
            })
            return ServiceResult(
                success=False,
                error=existing_validation.error,
                message=existing_validation.message,
                data=existing_validation.extra_data,
                status_code=409,
            )

        # Validar programa
        prog = db.session.query(Program).get(program_id)
        if not prog:
            log.warning("Programa no encontrado", extra_data={"program_id": program_id})
            return ServiceResult(
                success=False,
                error="program_not_found",
                message="Programa no encontrado",
                status_code=404,
            )

        # Validar slot
        slot_validation = self.validate_slot_for_appointment(slot_id, program_id, period.id)
        if not slot_validation.is_valid:
            log.warning("Slot inválido", extra_data={
                "slot_id": slot_id,
                "error": slot_validation.error,
            })
            return ServiceResult(
                success=False,
                error=slot_validation.error,
                message=slot_validation.message,
                data=slot_validation.extra_data,
                status_code=400 if slot_validation.error != "slot_unavailable" else 409,
            )
        slot = slot_validation.extra_data["slot"]

        # Transacción atómica: reservar slot
        try:
            updated = (
                db.session.query(TimeSlot)
                .filter(TimeSlot.id == slot_id, TimeSlot.is_booked == False)
                .update({TimeSlot.is_booked: True}, synchronize_session=False)
            )
            if updated != 1:
                log.warning("Conflicto al reservar slot", extra_data={"slot_id": slot_id})
                db.session.rollback()
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
            db.session.add(request_obj)
            db.session.flush()

            appointment = Appointment(
                request_id=request_obj.id,
                student_id=student.id,
                program_id=program_id,
                coordinator_id=slot.coordinator_id,
                slot_id=slot_id,
                status="SCHEDULED",
            )
            db.session.add(appointment)
            db.session.commit()

            log.info("Solicitud de cita creada exitosamente", extra_data={
                "request_id": request_obj.id,
                "appointment_id": appointment.id,
                "slot_day": str(slot.day),
                "slot_time": slot.start_time.strftime("%H:%M"),
                "coordinator_id": slot.coordinator_id,
            })

            # Notificaciones
            self._notify_slot_booked(slot)
            self._notify_appointment_created(request_obj, appointment, slot)
            self._notify_student_appointment_created(request_obj, appointment, slot, student)

            return ServiceResult(
                success=True,
                data={"request_id": request_obj.id, "appointment_id": appointment.id},
                status_code=200,
            )

        except IntegrityError as e:
            log.exception("Error de integridad al crear cita", extra_data={"error": str(e)})
            db.session.rollback()
            return ServiceResult(
                success=False,
                error="conflict",
                message="Error de integridad al crear la cita",
                status_code=409,
            )

    # ───────────────────────────────────────────────────────────────────────────
    # CANCELACIÓN
    # ───────────────────────────────────────────────────────────────────────────

    def cancel_request(self, request: Request, student: User) -> ServiceResult:
        """
        Cancela una solicitud del estudiante.
        
        Args:
            request: La solicitud a cancelar.
            student: El estudiante dueño de la solicitud.
            
        Returns:
            ServiceResult indicando el resultado de la operación.
        """
        log = self._log.bind(
            operation="cancel_request",
            student_id=student.id,
            request_id=request.id,
            request_type=request.type,
        )
        log.info("Iniciando cancelación de solicitud")

        # Validar que se puede cancelar
        validation = self.validate_can_cancel(request)
        if not validation.is_valid:
            log.warning("Cancelación rechazada", extra_data={
                "error": validation.error,
                "current_status": request.status,
            })
            status = 400 if validation.error == "not_pending" else 403
            return ServiceResult(
                success=False,
                error=validation.error,
                message=validation.message,
                status_code=status,
            )

        slot = None
        appointment = None

        # Procesar cancelación según tipo
        if request.type == "APPOINTMENT":
            appointment = (
                db.session.query(Appointment)
                .filter(Appointment.request_id == request.id)
                .first()
            )
            if appointment:
                slot = db.session.query(TimeSlot).get(appointment.slot_id)
                if slot and slot.is_booked:
                    slot.is_booked = False
                appointment.status = "CANCELED"

        request.status = "CANCELED"
        db.session.commit()

        log.info("Solicitud cancelada exitosamente", extra_data={
            "slot_released": slot.id if slot else None,
        })

        # Notificaciones
        if request.type == "APPOINTMENT" and slot:
            self._notify_slot_released(slot, appointment)
        self._notify_request_canceled(request, appointment)
        self._notify_student_canceled(request, student)

        return ServiceResult(success=True, data={"ok": True}, status_code=200)

    # ───────────────────────────────────────────────────────────────────────────
    # CONSULTAS
    # ───────────────────────────────────────────────────────────────────────────

    def get_student_requests(self, student: User) -> dict:
        """
        Obtiene las solicitudes de un estudiante.
        
        Args:
            student: Usuario estudiante.
            
        Returns:
            Diccionario con active_period, active (solicitud activa), 
            history (historial) y periods (períodos referenciados).
        """
        from sqlalchemy import and_, or_

        active_period = period_service.get_active_period()
        active_period_info = None
        student_admission_deadline = None

        if active_period:
            config = period_service.get_agendatec_config(active_period.id)
            active_period_info = {
                "id": active_period.id,
                "name": active_period.name,
                "status": active_period.status,
                "end_date": active_period.end_date.isoformat() if active_period.end_date else None,
            }
            if config and config.student_admission_deadline:
                student_admission_deadline = config.student_admission_deadline.isoformat()
                active_period_info["student_admission_deadline"] = student_admission_deadline

        # Solicitud activa (PENDING en período activo)
        active = None
        if active_period:
            active = (
                db.session.query(Request)
                .filter(
                    Request.student_id == student.id,
                    Request.period_id == active_period.id,
                    Request.status == "PENDING",
                )
                .order_by(Request.created_at.desc())
                .first()
            )

        # Historial
        history_query = db.session.query(Request).filter(Request.student_id == student.id)
        if active_period:
            history_query = history_query.filter(
                or_(
                    Request.status != "PENDING",
                    and_(Request.status == "PENDING", Request.period_id != active_period.id),
                )
            )
        history = history_query.order_by(Request.created_at.desc()).all()

        # Construir diccionario de períodos
        periods_dict = self._build_periods_dict(active, history, active_period)

        return {
            "active_period": active_period_info,
            "active": self._request_to_dict(active, periods_dict) if active else None,
            "history": [self._request_to_dict(r, periods_dict) for r in history],
            "periods": periods_dict,
        }

    # ───────────────────────────────────────────────────────────────────────────
    # MÉTODOS PRIVADOS - NOTIFICACIONES
    # ───────────────────────────────────────────────────────────────────────────

    def _notify_drop_created(self, request: Request, student: User) -> None:
        """Notifica a coordinadores sobre nueva solicitud de baja."""
        try:
            coord_ids = [
                row[0]
                for row in db.session.query(ProgramCoordinator.coordinator_id)
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
                broadcast_drop_created(self.socketio, cid, payload)
        except Exception:
            current_app.logger.exception("Failed to broadcast drop_created")

    def _notify_student_drop_created(self, request: Request, student: User) -> None:
        """Notifica al estudiante que su solicitud de baja fue creada."""
        try:
            n = create_notification(
                user_id=student.id,
                type="DROP_CREATED",
                title="Solicitud de baja creada",
                body="Tu solicitud de baja fue registrada.",
                data={"request_id": request.id},
                source_request_id=request.id,
                program_id=request.program_id,
            )
            db.session.commit()
            push_notification(self.socketio, student.id, n.to_dict())
        except Exception:
            current_app.logger.exception("Failed to create/push DROP notification")

    def _notify_slot_booked(self, slot: TimeSlot) -> None:
        """Emite evento de slot reservado."""
        try:
            slot_day = str(slot.day)
            room = f"day:{slot_day}"
            self.socketio.emit(
                "slot_booked",
                {
                    "slot_id": slot.id,
                    "day": slot_day,
                    "start_time": slot.start_time.strftime("%H:%M"),
                    "end_time": slot.end_time.strftime("%H:%M"),
                },
                to=room,
                namespace="/slots",
            )
            # Borrar hold si existía
            redis_cli = get_redis()
            redis_cli.delete(f"slot:{slot.id}:hold")
        except Exception:
            current_app.logger.exception("Failed to broadcast slot_booked")

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
            broadcast_appointment_created(self.socketio, appointment.coordinator_id, day_str, payload)
        except Exception:
            current_app.logger.exception("Failed to broadcast appointment_created")

    def _notify_student_appointment_created(
        self, request: Request, appointment: Appointment, slot: TimeSlot, student: User
    ) -> None:
        """Notifica al estudiante que su cita fue creada."""
        try:
            slot_day = str(slot.day)
            n = create_notification(
                user_id=student.id,
                type="APPOINTMENT_CREATED",
                title="Cita agendada",
                body=f"{slot_day} {slot.start_time.strftime('%H:%M')}–{slot.end_time.strftime('%H:%M')}",
                data={"request_id": request.id, "appointment_id": appointment.id, "day": slot_day},
                source_request_id=request.id,
                source_appointment_id=appointment.id,
                program_id=appointment.program_id,
            )
            db.session.commit()
            push_notification(self.socketio, student.id, n.to_dict())
        except Exception:
            current_app.logger.exception("Failed to create/push APPOINTMENT notification")

    def _notify_slot_released(self, slot: TimeSlot, appointment: Appointment) -> None:
        """Emite evento de slot liberado."""
        try:
            slot_day = str(slot.day)
            room = f"day:{slot_day}"
            self.socketio.emit(
                "slot_released",
                {
                    "slot_id": appointment.slot_id,
                    "day": slot_day,
                    "start_time": slot.start_time.strftime("%H:%M"),
                    "end_time": slot.end_time.strftime("%H:%M"),
                },
                to=room,
                namespace="/slots",
            )
            redis_cli = get_redis()
            redis_cli.delete(f"slot:{appointment.slot_id}:hold")
        except Exception:
            current_app.logger.exception("Failed to broadcast slot_released")

    def _notify_request_canceled(
        self, request: Request, appointment: Optional[Appointment]
    ) -> None:
        """Notifica a coordinadores sobre cancelación."""
        try:
            if request.type == "APPOINTMENT" and appointment:
                slot = db.session.query(TimeSlot).get(appointment.slot_id)
                day_str = str(slot.day) if slot else None
                payload = {
                    "type": "APPOINTMENT",
                    "request_id": request.id,
                    "new_status": request.status,
                    "day": day_str,
                    "program_id": request.program_id,
                }
                broadcast_request_status_changed(self.socketio, appointment.coordinator_id, payload)
            else:
                coord_ids = [
                    row[0]
                    for row in db.session.query(ProgramCoordinator.coordinator_id)
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
                    broadcast_request_status_changed(self.socketio, cid, payload)
        except Exception:
            current_app.logger.exception("Failed to broadcast request_status_changed")

    def _notify_student_canceled(self, request: Request, student: User) -> None:
        """Notifica al estudiante sobre la cancelación."""
        try:
            n = create_notification(
                user_id=student.id,
                type="APPOINTMENT_CANCELED" if request.type == "APPOINTMENT" else "REQUEST_STATUS_CHANGED",
                title="Solicitud cancelada",
                body="Has cancelado tu solicitud.",
                data={"request_id": request.id},
                source_request_id=request.id,
                program_id=request.program_id,
            )
            db.session.commit()
            push_notification(self.socketio, student.id, n.to_dict())
        except Exception:
            current_app.logger.exception("Failed to create/push CANCEL notification")

    # ───────────────────────────────────────────────────────────────────────────
    # MÉTODOS PRIVADOS - UTILIDADES
    # ───────────────────────────────────────────────────────────────────────────

    def _build_periods_dict(
        self,
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
                p = db.session.query(AcademicPeriod).get(pid)
                if p:
                    periods_dict[pid] = {
                        "id": p.id,
                        "name": p.name,
                        "status": p.status,
                    }

        return periods_dict

    def _request_to_dict(self, r: Request, periods_dict: dict) -> dict:
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
            ap = db.session.query(Appointment).filter(Appointment.request_id == r.id).first()
            if ap:
                sl = db.session.query(TimeSlot).get(ap.slot_id)
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


def get_request_service(socketio: Optional["SocketIO"] = None) -> RequestService:
    """
    Factory function para obtener instancia del servicio.
    
    Args:
        socketio: Instancia de SocketIO (opcional).
        
    Returns:
        Instancia de RequestService.
    """
    return RequestService(socketio)
