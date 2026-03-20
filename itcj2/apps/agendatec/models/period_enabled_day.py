from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class PeriodEnabledDay(Base):
    """
    Días habilitados para que estudiantes creen solicitudes en un período académico.
    """
    __tablename__ = "agendatec_period_enabled_days"

    id = Column(Integer, primary_key=True)

    period_id = Column(
        Integer,
        ForeignKey("core_academic_periods.id", ondelete="CASCADE"),
        nullable=False,
    )

    day = Column(Date, nullable=False)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)

    # Relaciones
    period = relationship("AcademicPeriod", back_populates="enabled_days")
    created_by = relationship("User", foreign_keys=[created_by_id])

    __table_args__ = (
        UniqueConstraint('period_id', 'day', name='uq_period_day'),
        Index('idx_period_enabled_days', 'period_id', 'day'),
    )

    def __repr__(self) -> str:
        return f"<PeriodEnabledDay period_id={self.period_id} day={self.day}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "period_id": self.period_id,
            "day": self.day.isoformat() if self.day else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "created_by_id": self.created_by_id,
        }
