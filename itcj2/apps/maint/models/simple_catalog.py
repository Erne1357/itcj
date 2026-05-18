"""
Catálogos simples del módulo de mantenimiento.

MaintMaintenanceType — tipos de mantenimiento (PREVENTIVO / CORRECTIVO)
MaintServiceOrigin   — origen del servicio     (INTERNO / EXTERNO)

Ambos catálogos son configurables desde la UI de administración y se
enlazan con MaintTicket por código (sin FK, para mantener la compatibilidad
con los strings hardcodeados actuales hasta que ticket_service.py sea refactorizado).
"""
from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import text

from itcj2.models.base import Base


class MaintMaintenanceType(Base):
    """
    Catálogo de tipos de mantenimiento.

    Valores estándar de code: PREVENTIVO | CORRECTIVO
    """
    __tablename__ = 'maint_maintenance_type'

    id = Column(Integer, primary_key=True)

    # --- Identificación ---
    code = Column(String(20), nullable=False)
    label = Column(String(60), nullable=False)

    # --- Orden y estado ---
    display_order = Column(Integer, nullable=False, server_default=text("0"))
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"))

    # --- Auditoría ---
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"),
                        onupdate=text("NOW()"))

    __table_args__ = (
        UniqueConstraint('code', name='uq_maint_maintenance_type_code'),
        Index('ix_maint_maintenance_type_code', 'code', unique=True),
        Index('ix_maint_maintenance_type_is_active', 'is_active'),
    )


class MaintServiceOrigin(Base):
    """
    Catálogo de orígenes del servicio de mantenimiento.

    Valores estándar de code: INTERNO | EXTERNO
    """
    __tablename__ = 'maint_service_origin'

    id = Column(Integer, primary_key=True)

    # --- Identificación ---
    code = Column(String(20), nullable=False)
    label = Column(String(60), nullable=False)

    # --- Orden y estado ---
    display_order = Column(Integer, nullable=False, server_default=text("0"))
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"))

    # --- Auditoría ---
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"),
                        onupdate=text("NOW()"))

    __table_args__ = (
        UniqueConstraint('code', name='uq_maint_service_origin_code'),
        Index('ix_maint_service_origin_code', 'code', unique=True),
        Index('ix_maint_service_origin_is_active', 'is_active'),
    )
