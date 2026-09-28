"""Convocatoria de titulación (una por periodo)."""
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey,
    Integer, String, Time,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class Cohort(Base):
    """Convocatoria por periodo. Agrupa procesos de titulación."""
    __tablename__ = "titulatec_cohorts"
    __table_args__ = (
        CheckConstraint("default_end_time > default_start_time",
                        name="ck_titulatec_cohorts_default_time_order"),
    )

    id = Column(Integer, primary_key=True)
    # Enlazado al período académico del core (una convocatoria por período).
    period_id = Column(
        Integer, ForeignKey("core_academic_periods.id"),
        unique=True, nullable=False, index=True,
    )
    name = Column(String(120), nullable=False)
    # Ventana del formulario PÚBLICO de inscripción (no del proceso). Fecha Y
    # hora, naive en hora local de APP_TZ: el mismo reloj que `db_now()` y que
    # `NOW()` de Postgres. NOT NULL desde tt20260927b (spec 2026-09-27 D9). El
    # cierre por omisión es 23:59:59 (se muestra «23:59»): quien envía a las
    # 23:59:30 del último día sigue dentro.
    opens_at = Column(DateTime, nullable=False)
    closes_at = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'open'"))  # draft|open|closed
    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)

    # --- Defaults de franja de cotejo ---------------------------------------
    # Los hereda cada dia habilitado que no los pise, y de ahi cada ventana que
    # abre un encargado. NOT NULL CON server_default: sin el, la migracion falla
    # sobre las convocatorias que ya existen.
    default_start_time = Column(Time, nullable=False, server_default=text("'09:00'"))
    default_end_time = Column(Time, nullable=False, server_default=text("'14:00'"))
    default_slot_minutes = Column(Integer, nullable=False, server_default=text("30"))
    default_capacity = Column(Integer, nullable=False, server_default=text("1"))
    default_location = Column(String(120), nullable=True)

    # LEGADO desde 2026-09-27: la aprobación automática se eliminó; la
    # columna queda sin uso. No quitar del modelo: el autogenerate propondría
    # borrarla.
    sii_auto_approve = Column(Boolean, nullable=False, server_default=text("true"))

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
