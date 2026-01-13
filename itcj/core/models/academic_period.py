from . import db
from sqlalchemy import CheckConstraint, Index
from datetime import datetime
from zoneinfo import ZoneInfo


class AcademicPeriod(db.Model):
    """
    Modelo para gestionar períodos académicos (semestres).

    Este modelo contiene SOLO información general del semestre que es compartida
    por todas las aplicaciones del sistema.

    Configuraciones específicas de cada aplicación (ej: AgendaTec) se almacenan
    en modelos separados relacionados a este período.

    Ejemplos de períodos:
    - "Ago-Dic 2025"
    - "Ene-Jun 2026"
    - "Verano 2026"
    """
    __tablename__ = "core_academic_periods"

    id = db.Column(db.Integer, primary_key=True)

    # Identificación del período
    name = db.Column(db.String(100), nullable=False, unique=True)
    # Ej: "Ago-Dic 2025", "Ene-Jun 2026"

    # Rango completo del semestre
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)

    # Estado del período
    # Solo un período puede estar ACTIVE a la vez (validado en aplicación)
    status = db.Column(
        db.Enum("ACTIVE", "INACTIVE", "ARCHIVED", name="period_status"),
        nullable=False,
        default="INACTIVE"
    )

    # Auditoría
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    created_by_id = db.Column(db.BigInteger, db.ForeignKey("core_users.id"), nullable=True)

    # Relaciones
    # Relación con configuración específica de AgendaTec
    agendatec_config = db.relationship(
        "AgendaTecPeriodConfig",
        back_populates="period",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    enabled_days = db.relationship(
        "PeriodEnabledDay",
        back_populates="period",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    requests = db.relationship(
        "Request",
        back_populates="period",
        cascade="all, delete",
        passive_deletes=True
    )

    created_by = db.relationship("User", foreign_keys=[created_by_id])

    # Constraints y validaciones
    __table_args__ = (
        # Validar que end_date >= start_date
        CheckConstraint('end_date >= start_date', name='check_period_dates'),

        # Índices para mejorar performance
        Index('idx_period_status', 'status'),
        Index('idx_period_dates', 'start_date', 'end_date'),
    )

    def __repr__(self) -> str:
        return f"<AcademicPeriod {self.id} '{self.name}' ({self.status})>"

    def to_dict(self) -> dict:
        """Serialización para API"""
        return {
            "id": self.id,
            "name": self.name,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by_id": self.created_by_id
        }

    @staticmethod
    def get_active():
        """
        Obtiene el período activo actual.

        Returns:
            AcademicPeriod | None: El período activo o None si no hay ninguno
        """
        return AcademicPeriod.query.filter_by(status="ACTIVE").first()


    def is_within_period(self, date) -> bool:
        """
        Verifica si una fecha está dentro del rango del período.

        Args:
            date: datetime.date o datetime.datetime

        Returns:
            bool: True si la fecha está en el rango [start_date, end_date]
        """
        if hasattr(date, 'date'):
            # Si es datetime, extraer solo la fecha
            date = date.date()

        return self.start_date <= date <= self.end_date
