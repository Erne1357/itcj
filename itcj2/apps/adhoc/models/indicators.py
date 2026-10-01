"""
Indicadores anuales con tablero de seguimiento por colores.

`AdhocIndicator` lleva 4 columnas de umbral planeado (`planned_white/red/
yellow/green`) en vez del `planned_value` concatenado con guiones del legacy
(`"b-r-a-v"`, que se rompía con cualquier umbral que contuviera un guion).
`frequency` es nullable a propósito: el legacy escribe `''` cuando no se
captura, y el CheckConstraint ya admite NULL por semántica SQL.
"""
from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class AdhocIndicatorYear(Base):
    __tablename__ = "adhoc_indicator_years"

    id = Column(Integer, primary_key=True)
    year = Column(Integer, nullable=False, unique=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    indicators = relationship(
        "AdhocIndicator", back_populates="year", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<AdhocIndicatorYear {self.year}>"


class AdhocIndicator(Base):
    __tablename__ = "adhoc_indicators"

    id = Column(Integer, primary_key=True)
    year_id = Column(Integer, ForeignKey("adhoc_indicator_years.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    process_id = Column(Integer, ForeignKey("adhoc_processes.id"), nullable=False, index=True)

    objective = Column(String(255), nullable=True)
    prev_results = Column(String(255), nullable=True)
    unit_calc = Column(String(255), nullable=True)
    responsible = Column(String(255), nullable=True)   # texto libre, NO FK a users (§2.2 del plan)
    facilitator = Column(String(255), nullable=True)   # texto libre, NO FK a users
    source = Column(String(255), nullable=True)
    strategic_rel = Column(Text, nullable=True)
    criteria = Column(Text, nullable=True)
    plan_b = Column(Text, nullable=True)
    document_url = Column(String(255), nullable=True)  # ruta relativa "{indicator_id}/{filename}"

    #: `tableros.tablero_id` del legacy. Idempotencia del ETL.
    legacy_id = Column(Integer, nullable=True, unique=True)

    frequency = Column(String(50), nullable=True)
    # Semanal | Mensual | Anual — nullable: el legacy escribe '' cuando no se captura.

    planned_white = Column(String(50), nullable=True)
    planned_red = Column(String(50), nullable=True)
    planned_yellow = Column(String(50), nullable=True)
    planned_green = Column(String(50), nullable=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    year = relationship("AdhocIndicatorYear", back_populates="indicators")
    process = relationship("AdhocProcess")
    trackings = relationship(
        "AdhocIndicatorTracking", back_populates="indicator", cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "frequency IN ('Semanal','Mensual','Anual')",
            name="ck_adhoc_indicators_frequency",
        ),
    )

    def __repr__(self) -> str:
        return f"<AdhocIndicator {self.id}>"


class AdhocIndicatorTracking(Base):
    __tablename__ = "adhoc_indicator_trackings"

    id = Column(Integer, primary_key=True)
    indicator_id = Column(Integer, ForeignKey("adhoc_indicators.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    period_index = Column(Integer, nullable=False)
    real_value = Column(String(100), nullable=True)
    color = Column(String(50), nullable=False, server_default=text("'blanco'"))
    # blanco (meta/estándar) | rojo (<70%) | amarillo (70-85%) | verde (>85%)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    indicator = relationship("AdhocIndicator", back_populates="trackings")

    __table_args__ = (
        CheckConstraint(
            "color IN ('blanco','rojo','amarillo','verde')",
            name="ck_adhoc_indicator_trackings_color",
        ),
        UniqueConstraint(
            "indicator_id", "period_index", name="uq_adhoc_indicator_trackings_indicator_period",
        ),
    )

    def __repr__(self) -> str:
        return f"<AdhocIndicatorTracking indicator={self.indicator_id} period={self.period_index}>"
