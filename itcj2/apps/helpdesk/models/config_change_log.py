"""
Modelo de auditoría para cambios en la configuración del módulo Helpdesk.
Registra quién cambió qué, cuándo, con snapshot before/after.
"""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class ConfigChangeLog(Base):
    """
    Log inmutable de cambios realizados desde la pestaña de Configuración.
    Acciones posibles: create | update | delete | toggle | reorder.
    Entidades: category | priority | status | area | notification | field_template | ...
    """
    __tablename__ = 'helpdesk_config_change_log'

    id = Column(BigInteger, primary_key=True)

    # --- Actor ---
    user_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False, index=True)

    # --- Qué cambió ---
    entity_type = Column(String(30), nullable=False, index=True)
    # category | priority | status | area | notification | field_template
    entity_id = Column(Integer, nullable=True)

    # --- Tipo de operación ---
    action = Column(String(20), nullable=False)
    # create | update | delete | toggle | reorder

    # --- Datos antes/después ---
    before_data = Column(JSON, nullable=True)
    after_data = Column(JSON, nullable=True)

    # --- Metadatos de auditoría ---
    changed_at = Column(DateTime, nullable=False, server_default=text("NOW()"), index=True)
    ip_address = Column(String(45), nullable=True)  # IPv4 o IPv6

    # --- Relaciones ---
    user = relationship('User', foreign_keys=[user_id])

    # --- Índices compuestos ---
    __table_args__ = (
        Index('ix_config_log_entity', 'entity_type', 'entity_id', 'changed_at'),
    )

    def __repr__(self):
        return f'<ConfigChangeLog {self.action} {self.entity_type}#{self.entity_id} by={self.user_id}>'

    def to_dict(self, include_user=False):
        data = {
            'id': self.id,
            'user_id': self.user_id,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'action': self.action,
            'before_data': self.before_data,
            'after_data': self.after_data,
            'changed_at': self.changed_at.isoformat() if self.changed_at else None,
            'ip_address': self.ip_address,
        }
        if include_user and self.user:
            data['user'] = {
                'id': self.user.id,
                'name': getattr(self.user, 'full_name', None) or str(self.user_id),
            }
        return data
