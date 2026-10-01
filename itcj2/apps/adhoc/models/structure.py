"""
Estructura organizativa de Calidad: áreas y procesos.

`AdhocArea` es propia de la app (D2: sin org-scoped authz, sin FK a
core_departments) — Calidad administra sus propias áreas con color para UI.
`AdhocProcess.color` es una columna real (el legacy la empacaba dentro de
`description` y la leía con una `@property`; aquí `description` vuelve a ser
una descripción de verdad).
"""
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Table, Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


adhoc_user_areas = Table(
    "adhoc_user_areas",
    Base.metadata,
    Column("user_id", BigInteger, ForeignKey("core_users.id", ondelete="CASCADE"), primary_key=True),
    Column("area_id", Integer, ForeignKey("adhoc_areas.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_adhoc_user_areas_area_id", "area_id"),
)


class AdhocArea(Base):
    """Área organizativa de Calidad (con color para UI)."""
    __tablename__ = "adhoc_areas"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    color = Column(String(7), nullable=False, server_default=text("'#4834d4'"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"), index=True)
    #: `areas.id_area` del legacy. Idempotencia del ETL.
    legacy_id = Column(Integer, nullable=True, unique=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    users = relationship("User", secondary=adhoc_user_areas)

    def __repr__(self) -> str:
        return f"<AdhocArea {self.name}>"


class AdhocProcess(Base):
    """Proceso de calidad. `color` es columna real (NOT NULL, con default),
    `description` es texto libre (hoy vacío en el legacy)."""
    __tablename__ = "adhoc_processes"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    color = Column(String(7), nullable=False, server_default=text("'#b2bec3'"))
    description = Column(Text, nullable=True)
    #: `procesos.id_proceso` del legacy. Idempotencia del ETL.
    legacy_id = Column(Integer, nullable=True, unique=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<AdhocProcess {self.name}>"
