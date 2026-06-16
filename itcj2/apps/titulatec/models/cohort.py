"""Convocatoria de titulación (una por periodo)."""
from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class Cohort(Base):
    """Convocatoria por periodo. Agrupa procesos de titulación."""
    __tablename__ = "titulatec_cohorts"

    id = Column(Integer, primary_key=True)
    # Enlazado al período académico del core (una convocatoria por período).
    period_id = Column(
        Integer, ForeignKey("core_academic_periods.id"),
        unique=True, nullable=False, index=True,
    )
    name = Column(String(120), nullable=False)
    opens_at = Column(Date, nullable=True)
    closes_at = Column(Date, nullable=True)                          # cierre de INSCRIPCIÓN (no del proceso)
    status = Column(String(20), nullable=False, server_default=text("'open'"))  # draft|open|closed
    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    academic_period = relationship("AcademicPeriod")
    processes = relationship("TitulationProcess", back_populates="cohort")

    @property
    def period_code(self) -> str | None:
        """Código del período académico ('2026A'). Usado en folio y rutas de archivos."""
        return self.academic_period.code if self.academic_period else None

    def __repr__(self) -> str:
        return f"<Cohort period_id={self.period_id}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "period_id": self.period_id,
            "period_code": self.period_code,
            "name": self.name,
            "opens_at": self.opens_at.isoformat() if self.opens_at else None,
            "closes_at": self.closes_at.isoformat() if self.closes_at else None,
            "status": self.status,
        }
