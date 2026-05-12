"""
Modelo para las plantillas de notificación del helpdesk (editable desde la UI).
Cada plantilla corresponde a un evento del ciclo de vida de tickets.
El helper notification_helper.py sigue usando strings hardcoded hasta una fase futura.
"""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class NotificationTemplate(Base):
    """
    Plantilla de notificación para un evento del ciclo de vida de tickets.
    El campo `code` identifica el evento que dispara la notificación.

    Eventos canónicos:
        ticket_created | ticket_assigned | ticket_reassigned | ticket_self_assigned |
        ticket_in_progress | ticket_resolved | ticket_rated | ticket_canceled |
        ticket_closed | comment_added

    Canal: inapp | email | both
    Las plantillas se crean exclusivamente por seed; no se permite add/delete desde la UI.
    """
    __tablename__ = 'helpdesk_notification_template'

    id = Column(BigInteger, primary_key=True)

    # --- Identificación ---
    code = Column(String(80), nullable=False, unique=True, index=True)
    # Valor canónico: ticket_created, ticket_assigned, comment_added, ...
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)

    # --- Canal de entrega ---
    channel = Column(String(20), nullable=False, default='inapp')
    # email | inapp | both

    # --- Contenido ---
    subject_template = Column(String(255), nullable=True)   # solo para email
    body_template = Column(Text, nullable=False)

    # --- Variables disponibles para la plantilla ---
    variables = Column(JSON, nullable=True)
    # ej: ["ticket", "requester", "assignee", "commenter"]

    # --- Auditoría ---
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, server_default=text("NOW()"))
    updated_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True, index=True)

    # --- Relaciones ---
    updated_by = relationship('User', foreign_keys=[updated_by_id])

    # --- Índices compuestos ---
    __table_args__ = (
        Index('ix_helpdesk_notification_template_active_code', 'is_active', 'code'),
    )

    def __repr__(self):
        return f'<NotificationTemplate {self.code}>'

    def to_dict(self, include_updated_by=False):
        data = {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'channel': self.channel,
            'subject_template': self.subject_template,
            'body_template': self.body_template,
            'variables': self.variables,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'updated_by_id': self.updated_by_id,
        }
        if include_updated_by and self.updated_by:
            data['updated_by'] = {
                'id': self.updated_by.id,
                'name': self.updated_by.full_name,
            }
        return data
