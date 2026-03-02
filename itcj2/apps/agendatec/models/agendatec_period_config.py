from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class AgendaTecPeriodConfig(Base):
    """
    Configuración específica de AgendaTec para un período académico.
    Relación 1:1 con AcademicPeriod.
    """
    __tablename__ = "agendatec_period_config"

    id = Column(Integer, primary_key=True)

    period_id = Column(
        Integer,
        ForeignKey("core_academic_periods.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    student_admission_start = Column(DateTime(timezone=True), nullable=False)
    student_admission_deadline = Column(DateTime(timezone=True), nullable=False)

    max_cancellations_per_student = Column(Integer, nullable=False, default=2)

    allow_drop_requests = Column(Boolean, nullable=False, default=True)
    allow_appointment_requests = Column(Boolean, nullable=False, default=True)

    # Auditoría
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)

    # Relaciones
    period = relationship("AcademicPeriod", back_populates="agendatec_config")
    created_by = relationship("User", foreign_keys=[created_by_id])

    __table_args__ = (
        Index('idx_agendatec_period_config_period', 'period_id'),
    )

    def __repr__(self) -> str:
        return f"<AgendaTecPeriodConfig period_id={self.period_id}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "period_id": self.period_id,
            "student_admission_start": self.student_admission_start.isoformat() if self.student_admission_start else None,
            "student_admission_deadline": self.student_admission_deadline.isoformat() if self.student_admission_deadline else None,
            "max_cancellations_per_student": self.max_cancellations_per_student,
            "allow_drop_requests": self.allow_drop_requests,
            "allow_appointment_requests": self.allow_appointment_requests,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by_id": self.created_by_id,
        }

    def is_student_window_open(self) -> bool:
        if not self.period or self.period.status != "ACTIVE":
            return False
        tz = ZoneInfo("America/Ciudad_Juarez")
        now = datetime.now(tz)
        return self.student_admission_start <= now <= self.student_admission_deadline

    def get_window_status(self) -> dict:
        tz = ZoneInfo("America/Ciudad_Juarez")
        now = datetime.now(tz)

        if not self.period or self.period.status != "ACTIVE":
            return {
                "is_open": False,
                "reason": "period_not_active",
                "starts_at": self.student_admission_start.isoformat() if self.student_admission_start else None,
                "ends_at": self.student_admission_deadline.isoformat() if self.student_admission_deadline else None,
            }
        if now < self.student_admission_start:
            return {
                "is_open": False,
                "reason": "window_not_started",
                "starts_at": self.student_admission_start.isoformat(),
                "ends_at": self.student_admission_deadline.isoformat(),
            }
        if now > self.student_admission_deadline:
            return {
                "is_open": False,
                "reason": "window_closed",
                "starts_at": self.student_admission_start.isoformat(),
                "ends_at": self.student_admission_deadline.isoformat(),
            }
        return {
            "is_open": True,
            "reason": "window_open",
            "starts_at": self.student_admission_start.isoformat(),
            "ends_at": self.student_admission_deadline.isoformat(),
        }

    def can_request_type(self, request_type: str) -> bool:
        if request_type == "DROP":
            return self.allow_drop_requests
        elif request_type == "APPOINTMENT":
            return self.allow_appointment_requests
        return False
