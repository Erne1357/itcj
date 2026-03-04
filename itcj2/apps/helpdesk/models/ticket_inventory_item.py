"""
Modelo para relación many-to-many entre tickets y equipos de inventario
"""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from itcj2.models.base import Base


class TicketInventoryItem(Base):
    """
    Tabla intermedia para relacionar tickets con múltiples equipos del inventario.
    Un ticket puede afectar a varios equipos (ej: problema en computadoras de un salón).
    Un equipo puede tener múltiples tickets a lo largo del tiempo.
    """
    __tablename__ = "helpdesk_ticket_inventory_items"

    id = Column(Integer, primary_key=True)

    ticket_id = Column(Integer, ForeignKey("helpdesk_ticket.id"), nullable=False, index=True)
    inventory_item_id = Column(Integer, ForeignKey("helpdesk_inventory_items.id"), nullable=False, index=True)

    # Timestamp de cuándo se agregó el equipo al ticket
    added_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relaciones
    ticket = relationship("Ticket", back_populates="ticket_items")
    inventory_item = relationship("InventoryItem", back_populates="ticket_items")

    __table_args__ = (
        UniqueConstraint("ticket_id", "inventory_item_id", name="uq_ticket_item"),
        Index("ix_ticket_inventory_ticket", "ticket_id"),
        Index("ix_ticket_inventory_item", "inventory_item_id"),
    )

    def __repr__(self):
        return f"<TicketInventoryItem Ticket:{self.ticket_id} Item:{self.inventory_item_id}>"

    def to_dict(self):
        return {
            'id': self.id,
            'ticket_id': self.ticket_id,
            'inventory_item_id': self.inventory_item_id,
            'inventory_item': self.inventory_item.to_dict() if self.inventory_item else None,
            'added_at': self.added_at.isoformat() if self.added_at else None,
        }
