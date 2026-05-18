"""
Modelo para el catálogo de plantillas de notificación de mantenimiento.

Permite editar desde la UI los asuntos, títulos y cuerpos de las
notificaciones transaccionales (in-app y/o email) del ciclo de vida
de los tickets, sin necesidad de despliegue de código.

Flujo: ticket_created → ticket_assigned → ticket_in_progress →
       ticket_resolved → ticket_rated
Eventos laterales: ticket_canceled, ticket_comment, ticket_overdue_sla
"""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class MaintNotificationTemplate(Base):
    """
    Catálogo de plantillas de notificación para eventos de tickets maint.

    Canales: inapp | email | both
    Los cuerpos usan sintaxis Jinja2 con las variables listadas en `variables`.
    """
    __tablename__ = 'maint_notification_template'

    id = Column(Integer, primary_key=True)

    # --- Identificación ---
    code = Column(String(80), nullable=False)
    name = Column(String(120), nullable=False)

    # --- Canal ---
    channel = Column(String(20), nullable=False, server_default=text("'inapp'"))
    # inapp | email | both

    # --- Contenido de email ---
    subject_template = Column(String(255), nullable=True)

    # --- Contenido in-app ---
    title_template = Column(String(255), nullable=True)

    # --- Cuerpo (compartido o in-app) ---
    body_template = Column(Text, nullable=False)

    # --- Metadatos de variables disponibles ---
    variables = Column(JSON, nullable=True)
    # Ej: ["ticket", "requester", "technician"]

    # --- Estado ---
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"))

    # --- Auditoría ---
    updated_at = Column(DateTime, server_default=text("NOW()"), onupdate=text("NOW()"))
    updated_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)

    # --- Relaciones ---
    updated_by = relationship('User', foreign_keys=[updated_by_id])

    __table_args__ = (
        UniqueConstraint('code', name='uq_maint_notification_template_code'),
        Index('ix_maint_notification_template_code', 'code', unique=True),
        Index('ix_maint_notification_template_is_active', 'is_active'),
    )
