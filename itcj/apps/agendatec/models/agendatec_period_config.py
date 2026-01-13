from . import db
from sqlalchemy import UniqueConstraint, Index
from datetime import datetime
from zoneinfo import ZoneInfo


class AgendaTecPeriodConfig(db.Model):
    """
    Configuración específica de AgendaTec para un período académico.

    Este modelo separa las configuraciones específicas de AgendaTec del modelo
    general de períodos académicos (AcademicPeriod) que vive en core.

    Esto permite que otras aplicaciones tengan sus propias configuraciones
    por período sin afectar AgendaTec.

    Relación 1:1 con AcademicPeriod.
    """
    __tablename__ = "agendatec_period_config"

    id = db.Column(db.Integer, primary_key=True)

    # Relación única con el período académico
    period_id = db.Column(
        db.Integer,
        db.ForeignKey("core_academic_periods.id", ondelete="CASCADE"),
        nullable=False,
        unique=True
    )

    # Ventana de admisión para estudiantes
    # Después de esta fecha/hora, los estudiantes no pueden crear solicitudes
    student_admission_deadline = db.Column(db.DateTime(timezone=True), nullable=False)
    # Ej: "2025-08-27 18:00:00-07:00"

    # Límite de cancelaciones por estudiante por período
    # Si el estudiante cancela más de este número, no puede cancelar más
    max_cancellations_per_student = db.Column(db.Integer, nullable=False, default=2)

    # Tipos de solicitudes habilitadas
    allow_drop_requests = db.Column(db.Boolean, nullable=False, default=True)
    allow_appointment_requests = db.Column(db.Boolean, nullable=False, default=True)

    # Auditoría
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    created_by_id = db.Column(db.BigInteger, db.ForeignKey("core_users.id"), nullable=True)

    # Relaciones
    period = db.relationship("AcademicPeriod", back_populates="agendatec_config")
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    # Constraints
    __table_args__ = (
        # Índice para búsquedas rápidas
        Index('idx_agendatec_period_config_period', 'period_id'),
    )

    def __repr__(self) -> str:
        return f"<AgendaTecPeriodConfig period_id={self.period_id}>"

    def to_dict(self) -> dict:
        """Serialización para API"""
        return {
            "id": self.id,
            "period_id": self.period_id,
            "student_admission_deadline": self.student_admission_deadline.isoformat() if self.student_admission_deadline else None,
            "max_cancellations_per_student": self.max_cancellations_per_student,
            "allow_drop_requests": self.allow_drop_requests,
            "allow_appointment_requests": self.allow_appointment_requests,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by_id": self.created_by_id
        }

    def is_student_window_open(self) -> bool:
        """
        Verifica si la ventana de admisión para estudiantes está abierta.

        Condiciones:
        - El período asociado debe estar ACTIVE
        - La fecha/hora actual debe ser <= student_admission_deadline

        Returns:
            bool: True si la ventana está abierta, False en caso contrario
        """
        if not self.period or self.period.status != "ACTIVE":
            return False

        tz = ZoneInfo("America/Ciudad_Juarez")
        now = datetime.now(tz)

        return now <= self.student_admission_deadline

    def can_request_type(self, request_type: str) -> bool:
        """
        Verifica si un tipo de solicitud está habilitado.

        Args:
            request_type: "DROP" o "APPOINTMENT"

        Returns:
            bool: True si el tipo está habilitado
        """
        if request_type == "DROP":
            return self.allow_drop_requests
        elif request_type == "APPOINTMENT":
            return self.allow_appointment_requests
        return False
