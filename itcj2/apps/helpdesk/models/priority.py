"""
Modelo para el catálogo de prioridades de tickets (editable desde la UI).
Reemplaza las listas hardcoded en ticket_service.py y los SLA en ticket.py.
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import text

from itcj2.models.base import Base


class Priority(Base):
    """
    Catálogo de prioridades de ticket con SLA asociado.
    Orden de urgencia: BAJA → MEDIA → ALTA → URGENTE.
    """
    __tablename__ = 'helpdesk_priority'

    id = Column(Integer, primary_key=True)

    # --- Identificación ---
    code = Column(String(20), nullable=False, unique=True, index=True)
    # Valores canónicos: BAJA | MEDIA | ALTA | URGENTE
    label = Column(String(50), nullable=False)

    # --- Presentación ---
    color = Column(String(20), nullable=True)         # hex o nombre CSS, ej: #dc3545
    badge_class = Column(String(50), nullable=True)   # clase Bootstrap, ej: bg-danger

    # --- SLA ---
    sla_hours = Column(Integer, nullable=False, default=72)  # horas hasta vencimiento

    # --- Ordenamiento ---
    display_order = Column(Integer, default=0)

    # --- Auditoría ---
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, server_default=text("NOW()"))

    def __repr__(self):
        return f'<Priority {self.code} sla={self.sla_hours}h>'

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'label': self.label,
            'color': self.color,
            'badge_class': self.badge_class,
            'sla_hours': self.sla_hours,
            'display_order': self.display_order,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
