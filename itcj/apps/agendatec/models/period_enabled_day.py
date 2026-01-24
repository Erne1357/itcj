from . import db
from sqlalchemy import UniqueConstraint, Index


class PeriodEnabledDay(db.Model):
    """
    Días habilitados para que estudiantes creen solicitudes en un período académico.

    Este modelo permite configurar dinámicamente qué días específicos están
    disponibles para que los estudiantes creen solicitudes (citas o bajas).

    Anteriormente, estos días estaban hardcodeados en el código como:
    ALLOWED_DAYS = {date(2025, 8, 25), date(2025, 8, 26), date(2025, 8, 27)}

    Ahora son configurables desde la pantalla administrativa.
    """
    __tablename__ = "agendatec_period_enabled_days"

    id = db.Column(db.Integer, primary_key=True)

    # Relación con el período académico
    period_id = db.Column(
        db.Integer,
        db.ForeignKey("core_academic_periods.id", ondelete="CASCADE"),
        nullable=False
    )

    # Día específico habilitado
    day = db.Column(db.Date, nullable=False)

    # Auditoría
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    created_by_id = db.Column(db.BigInteger, db.ForeignKey("core_users.id"), nullable=True)

    # Relaciones
    period = db.relationship("AcademicPeriod", back_populates="enabled_days")
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    # Constraints
    __table_args__ = (
        # Un día no puede estar duplicado en el mismo período
        UniqueConstraint('period_id', 'day', name='uq_period_day'),

        # Índice compuesto para búsquedas rápidas
        Index('idx_period_enabled_days', 'period_id', 'day'),
    )

    def __repr__(self) -> str:
        return f"<PeriodEnabledDay period_id={self.period_id} day={self.day}>"

    def to_dict(self) -> dict:
        """Serialización para API"""
        return {
            "id": self.id,
            "period_id": self.period_id,
            "day": self.day.isoformat() if self.day else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "created_by_id": self.created_by_id
        }
