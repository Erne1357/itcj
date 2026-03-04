"""
Modelo para historial de cambios en equipos del inventario
"""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from itcj2.models.base import Base


class InventoryHistory(Base):
    """
    Registro de todos los cambios en equipos del inventario.
    Proporciona trazabilidad completa: quién, cuándo, qué cambió y por qué.
    """
    __tablename__ = "helpdesk_inventory_history"

    id = Column(Integer, primary_key=True)

    item_id = Column(Integer, ForeignKey("helpdesk_inventory_items.id"), nullable=False, index=True)

    # Tipo de evento
    event_type = Column(String(50), nullable=False, index=True)

    # Datos del cambio (JSON flexible)
    old_value = Column(JSON)
    new_value = Column(JSON)

    # Contexto y observaciones
    notes = Column(Text)

    # Relación con ticket (si aplica)
    related_ticket_id = Column(Integer, ForeignKey("helpdesk_ticket.id"), nullable=True)

    # Auditoría
    performed_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False)

    timestamp = Column(DateTime, server_default=func.now(), nullable=False, index=True)

    ip_address = Column(String(50))

    # Relaciones
    item = relationship("InventoryItem", back_populates="history")
    performed_by = relationship("User", backref="inventory_actions")
    related_ticket = relationship("Ticket", backref="inventory_history_entries")

    __table_args__ = (
        Index("ix_inventory_history_item_timestamp", "item_id", "timestamp"),
        Index("ix_inventory_history_event_timestamp", "event_type", "timestamp"),
    )

    def __repr__(self):
        return f"<InventoryHistory {self.event_type} on item {self.item_id} at {self.timestamp}>"

    def to_dict(self, include_relations=False):
        data = {
            'id': self.id,
            'item_id': self.item_id,
            'event_type': self.event_type,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'notes': self.notes,
            'related_ticket_id': self.related_ticket_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'ip_address': self.ip_address,
        }
        if include_relations:
            data['performed_by'] = {
                'id': self.performed_by.id,
                'full_name': self.performed_by.full_name,
                'email': self.performed_by.email,
            } if self.performed_by else None
            data['related_ticket'] = {
                'id': self.related_ticket.id,
                'ticket_number': self.related_ticket.ticket_number,
                'title': self.related_ticket.title,
            } if self.related_ticket else None
        return data

    @staticmethod
    def get_event_description(event_type):
        """Descripción legible del tipo de evento"""
        descriptions = {
            'REGISTERED': 'Equipo registrado',
            'ASSIGNED_TO_DEPT': 'Asignado al departamento',
            'ASSIGNED_TO_USER': 'Asignado a usuario',
            'UNASSIGNED': 'Liberado',
            'REASSIGNED': 'Reasignado',
            'LOCATION_CHANGED': 'Ubicación actualizada',
            'STATUS_CHANGED': 'Estado modificado',
            'MAINTENANCE_SCHEDULED': 'Mantenimiento programado',
            'MAINTENANCE_COMPLETED': 'Mantenimiento completado',
            'SPECS_UPDATED': 'Especificaciones actualizadas',
            'TRANSFERRED': 'Transferido a otro departamento',
            'DEACTIVATED': 'Dado de baja',
            'REACTIVATED': 'Reactivado',
        }
        return descriptions.get(event_type, event_type)
