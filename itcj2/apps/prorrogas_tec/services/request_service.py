"""
Servicio de solicitudes de plazos de pago para Prorrogas_tec.
Patrón basado en itcj2/apps/agendatec/services/request_service.py.

Centraliza la lógica de negocio para gestión de solicitudes de plazos de pago:
- Validaciones de creación (período/admisión, programa, opción de pago, duplicados)
- Creación de solicitudes
- Cancelación de solicitudes
- Consulta de solicitudes del estudiante
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from itcj2.apps.prorrogas_tec.models.request import Request_pro
from itcj2.apps.prorrogas_tec.models.payment_options import Payments_options
from itcj2.core.models.user import User

logger = logging.getLogger(__name__)

MAX_PAYMENT_TERMS = 3


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


class RequestProService:
    """
    Servicio para gestión de solicitudes de plazos de pago.

    Encapsula la lógica de negocio relacionada con:
    - Creación de solicitudes de plazos de pago
    - Cancelación de solicitudes
    - Validaciones de programa, opción de pago activa, duplicados
    """

    # ───────────────────────────────────────────────────────────────────────────
    # VALIDACIONES
    # ───────────────────────────────────────────────────────────────────────────

    def validate_payments_terms(self, payments_terms: int) -> ValidationResult:
        """Valida que el número de plazos esté en el rango permitido."""
        if not payments_terms or payments_terms < 1 or payments_terms > MAX_PAYMENT_TERMS:
            return ValidationResult(
                is_valid=False,
                error="invalid_payments_terms",
                message=f"El número de plazos debe estar entre 1 y {MAX_PAYMENT_TERMS}.",
            )
        return ValidationResult(is_valid=True)

    def validate_letter(self, letter: str) -> ValidationResult:
        """Valida que la justificación no esté vacía."""
        if not letter or not letter.strip():
            return ValidationResult(
                is_valid=False,
                error="letter_required",
                message="La justificación es obligatoria.",
            )
        return ValidationResult(is_valid=True)

    def validate_program_exists(self, db: Session, program_id: int) -> ValidationResult:
        """
        Valida que program_id exista en el catálogo de programas.
        No hay relación estudiante↔programa en el sistema: el estudiante
        elige su programa manualmente en el formulario, así que aquí solo
        se valida que el id enviado sea un programa real.
        """
        from itcj2.core.models.program import Program

        program = db.get(Program, program_id)
        if not program:
            return ValidationResult(
                is_valid=False,
                error="program_not_found",
                message="El programa seleccionado no existe.",
            )
        return ValidationResult(is_valid=True)

    def validate_active_payment_option(self, db: Session) -> ValidationResult:
        """Valida que exista una opción de pago activa y la retorna."""
        option = (
            db.query(Payments_options)
            .filter(Payments_options.status.is_(True))
            .order_by(Payments_options.period_id.desc(), Payments_options.created_at.desc())
            .first()
        )
        if not option:
            return ValidationResult(
                is_valid=False,
                error="no_active_payment_option",
                message="No hay una opción de pago activa en este momento.",
            )
        return ValidationResult(is_valid=True, extra_data={"option": option})

    def validate_no_existing_pending_request(
        self, db: Session, student_id: int
    ) -> ValidationResult:
        """Valida que el estudiante no tenga ya una solicitud PENDING."""
        existing = (
            db.query(Request_pro)
            .filter(Request_pro.student_id == student_id, Request_pro.status == "PENDING")
            .first()
        )
        if existing:
            return ValidationResult(
                is_valid=False,
                error="already_has_pending_request",
                message="Ya tienes una solicitud de plazos de pago pendiente.",
                extra_data={"existing_request_id": existing.id},
            )
        return ValidationResult(is_valid=True)

    def validate_can_cancel(self, request: Request_pro) -> ValidationResult:
        """Valida que una solicitud pueda ser cancelada."""
        if request.status != "PENDING":
            return ValidationResult(
                is_valid=False,
                error="not_pending",
                message="Solo se pueden cancelar solicitudes en estado PENDING.",
            )
        return ValidationResult(is_valid=True)

    # ───────────────────────────────────────────────────────────────────────────
    # CREACIÓN
    # ───────────────────────────────────────────────────────────────────────────

    def create_payment_plan_request(
        self,
        db: Session,
        student: User,
        program_id: int,
        payments_terms: int,
        letter: str,
    ) -> ServiceResult:
        """Crea una nueva solicitud de plazos de pago."""
        logger.info("Iniciando creación de solicitud de plazos de pago", extra={
            "student_id": student.id, "program_id": program_id
        })

        terms_validation = self.validate_payments_terms(payments_terms)
        if not terms_validation.is_valid:
            return ServiceResult(
                success=False,
                error=terms_validation.error,
                message=terms_validation.message,
                status_code=400,
            )

        letter_validation = self.validate_letter(letter)
        if not letter_validation.is_valid:
            return ServiceResult(
                success=False,
                error=letter_validation.error,
                message=letter_validation.message,
                status_code=400,
            )

        program_validation = self.validate_program_exists(db, program_id)
        if not program_validation.is_valid:
            return ServiceResult(
                success=False,
                error=program_validation.error,
                message=program_validation.message,
                status_code=404,
            )

        option_validation = self.validate_active_payment_option(db)
        if not option_validation.is_valid:
            return ServiceResult(
                success=False,
                error=option_validation.error,
                message=option_validation.message,
                status_code=503,
            )
        option = option_validation.extra_data["option"]

        existing_validation = self.validate_no_existing_pending_request(db, student.id)
        if not existing_validation.is_valid:
            return ServiceResult(
                success=False,
                error=existing_validation.error,
                message=existing_validation.message,
                data=existing_validation.extra_data,
                status_code=409,
            )

        try:
            request_obj = Request_pro(
                student_id=student.id,
                program_id=program_id,
                period_id=option.period_id,
                total_amount_id=option.id,
                letter=letter.strip(),
                payments_terms=payments_terms,
                status="PENDING",
            )
            db.add(request_obj)
            db.commit()
            db.refresh(request_obj)

            logger.info("Solicitud de plazos de pago creada", extra={
                "request_id": request_obj.id, "student_id": student.id
            })

            return ServiceResult(
                success=True,
                data={"request_id": request_obj.id},
                status_code=200,
            )
        except IntegrityError as e:
            logger.exception("Error de integridad al crear solicitud", extra={"error": str(e)})
            db.rollback()
            return ServiceResult(
                success=False,
                error="conflict",
                message="Error de integridad al crear la solicitud.",
                status_code=409,
            )

    # ───────────────────────────────────────────────────────────────────────────
    # CANCELACIÓN
    # ───────────────────────────────────────────────────────────────────────────

    def cancel_request(self, db: Session, request: Request_pro, student: User) -> ServiceResult:
        """Cancela una solicitud del estudiante."""
        logger.info("Iniciando cancelación de solicitud", extra={
            "student_id": student.id, "request_id": request.id
        })

        validation = self.validate_can_cancel(request)
        if not validation.is_valid:
            return ServiceResult(
                success=False,
                error=validation.error,
                message=validation.message,
                status_code=400,
            )

        db.delete(request)
        db.commit()

        logger.info("Solicitud de plazos de pago cancelada", extra={"request_id": request.id})

        return ServiceResult(success=True, data={"ok": True}, status_code=200)

    # ───────────────────────────────────────────────────────────────────────────
    # CONSULTAS
    # ───────────────────────────────────────────────────────────────────────────

    def get_student_requests(self, db: Session, student: User) -> dict:
        """Obtiene las solicitudes de plazos de pago de un estudiante."""
        active = (
            db.query(Request_pro)
            .filter(Request_pro.student_id == student.id, Request_pro.status == "PENDING")
            .order_by(Request_pro.created_at.desc())
            .first()
        )
        history = (
            db.query(Request_pro)
            .filter(Request_pro.student_id == student.id, Request_pro.status != "PENDING")
            .order_by(Request_pro.created_at.desc())
            .all()
        )
        return {
            "active": self._request_to_dict(active) if active else None,
            "history": [self._request_to_dict(r) for r in history],
        }

    # ───────────────────────────────────────────────────────────────────────────
    # UTILIDADES PRIVADAS
    # ───────────────────────────────────────────────────────────────────────────

    def _request_to_dict(self, r: Request_pro) -> dict:
        return {
            "id": r.id,
            "program_id": r.program_id,
            "period_id": r.period_id,
            "total_amount_id": r.total_amount_id,
            "payments_terms": r.payments_terms,
            "letter": r.letter,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# INSTANCIA SINGLETON
# ═══════════════════════════════════════════════════════════════════════════════


def get_request_pro_service() -> RequestProService:
    """Factory function para obtener instancia del servicio."""
    return RequestProService()