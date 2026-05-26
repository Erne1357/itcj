"""
Modelo de auditoría para cambios en la configuración del módulo de mantenimiento.

Registra cada create/update/delete/toggle/reorder sobre entidades de configuración
(prioridades, tipos, orígenes, áreas, categorías, plantillas, notificaciones).
"""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class MaintConfigChangeLog(Base):
    """
    Log de auditoría para operaciones de configuración de mantenimiento.

    entity_type válidos:
        priority | maint_type | service_origin | area | category |
        field_template | notification

    action válidos:
        create | update | delete | toggle | reorder
    """
    __tablename__ = 'maint_config_change_log'

    id = Column(BigInteger, primary_key=True)

    # --- Quién y cuándo ---
    user_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False, index=True)
    changed_at = Column(DateTime, nullable=False, server_default=text("NOW()"), index=True)

    # --- Qué entidad ---
    entity_type = Column(String(30), nullable=False, index=True)
    entity_id = Column(Integer, nullable=True)

    # --- Qué operación ---
    action = Column(String(20), nullable=False)

    # --- Snapshot antes/después ---
    before_data = Column(JSON, nullable=True)
    after_data = Column(JSON, nullable=True)

    # --- Contexto de red ---
    ip_address = Column(String(45), nullable=True)

    # --- Relaciones ---
    user = relationship('User', foreign_keys=[user_id])

    __table_args__ = (
        Index('ix_maint_config_log_entity', 'entity_type', 'entity_id', 'changed_at'),
    )
