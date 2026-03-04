from sqlalchemy import (
    BigInteger, CheckConstraint, Column, Date, DateTime,
    Enum, ForeignKey, Index, Integer, String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class AcademicPeriod(Base):
    """
    Períodos académicos (semestres).

    Contiene información general compartida por todas las aplicaciones.
    Configuraciones específicas de cada app (ej: AgendaTec) se almacenan
    en modelos relacionados.
    """
    __tablename__ = "core_academic_periods"

    id = Column(Integer, primary_key=True)
    code = Column(String(6), nullable=False, unique=True)
    name = Column(String(100), nullable=False, unique=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(
        Enum("ACTIVE", "INACTIVE", "ARCHIVED", name="period_status"),
        nullable=False,
        default="INACTIVE",
    )
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)

    agendatec_config = relationship(
        "AgendaTecPeriodConfig",
        back_populates="period",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    enabled_days = relationship(
        "PeriodEnabledDay",
        back_populates="period",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    requests = relationship(
        "Request",
        back_populates="period",
        cascade="all, delete",
        passive_deletes=True,
    )
    created_by = relationship("User", foreign_keys=[created_by_id])

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="check_period_dates"),
        Index("idx_period_status", "status"),
        Index("idx_period_dates", "start_date", "end_date"),
    )

    def __repr__(self) -> str:
        return f"<AcademicPeriod {self.id} '{self.name}' ({self.status})>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by_id": self.created_by_id,
        }

    @staticmethod
    def get_active(db):
        """Obtiene el período activo. Requiere una sesión SQLAlchemy."""
        return db.query(AcademicPeriod).filter_by(status="ACTIVE").first()

    def is_within_period(self, date) -> bool:
        if hasattr(date, "date"):
            date = date.date()
        return self.start_date <= date <= self.end_date
