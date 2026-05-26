"""
Modelo para el catálogo de áreas técnicas de mantenimiento.

Permite configurar desde la UI las áreas (TRANSPORT/ELECTRICAL/CARPENTRY/AC/GARDENING/GENERAL/PAINTING).
El campo code es el identificador estable; MaintTechnicianArea.area_code lo referencia
por string sin FK rígida para mantener compatibilidad.
"""
from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import text

from itcj2.models.base import Base


class MaintArea(Base):
    """
    Catálogo de áreas técnicas de mantenimiento.

    Valores estándar de code:
        TRANSPORT | ELECTRICAL | CARPENTRY | AC | GARDENING | GENERAL | PAINTING

    MaintTechnicianArea.area_code referencia este catálogo por código (string),
    sin FK explícita, para preservar compatibilidad con datos existentes.
    """
    __tablename__ = 'maint_area'

    id = Column(Integer, primary_key=True)

    # --- Identificación ---
    code = Column(String(30), nullable=False)
    label = Column(String(80), nullable=False)

    # --- Presentación visual ---
    icon = Column(String(60), nullable=True)        # ej: 'bi-truck'
    color = Column(String(20), nullable=True)       # ej: '#1565c0'

    # --- Descripción ---
    description = Column(Text, nullable=True)

    # --- Orden y estado ---
    display_order = Column(Integer, nullable=False, server_default=text("0"))
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"))

    # --- Auditoría ---
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"),
                        onupdate=text("NOW()"))

    __table_args__ = (
        UniqueConstraint('code', name='uq_maint_area_code'),
        Index('ix_maint_area_code', 'code', unique=True),
        Index('ix_maint_area_is_active', 'is_active'),
    )
