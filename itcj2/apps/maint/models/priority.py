"""
Modelo para el catálogo de prioridades de mantenimiento.

Permite configurar desde la UI las prioridades (BAJA/MEDIA/ALTA/URGENTE),
sus SLA en horas, colores y clases Bootstrap para badges.
"""
from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import text

from itcj2.models.base import Base


class MaintPriority(Base):
    """
    Catálogo de prioridades de tickets de mantenimiento.

    Valores estándar de code: BAJA | MEDIA | ALTA | URGENTE
    El campo sla_hours reemplaza el dict SLA_HOURS hardcoded en ticket.py
    (la migración de ticket_service.py leerá este catálogo; ese refactor
    es tarea del siguiente paso de Fase 3).
    """
    __tablename__ = 'maint_priority'

    id = Column(Integer, primary_key=True)

    # --- Identificación ---
    code = Column(String(20), nullable=False)
    label = Column(String(50), nullable=False)

    # --- Presentación visual ---
    color = Column(String(20), nullable=True)           # ej: '#c62828'
    badge_class = Column(String(50), nullable=True)     # ej: 'bg-danger'

    # --- SLA ---
    sla_hours = Column(Integer, nullable=False, server_default=text("72"))

    # --- Orden y estado ---
    is_default = Column(Boolean, nullable=False, server_default=text("FALSE"))
    display_order = Column(Integer, nullable=False, server_default=text("0"))
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"))

    # --- Auditoría ---
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"),
                        onupdate=text("NOW()"))

    __table_args__ = (
        UniqueConstraint('code', name='uq_maint_priority_code'),
        Index('ix_maint_priority_code', 'code', unique=True),
        Index('ix_maint_priority_is_active', 'is_active'),
    )
