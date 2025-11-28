"""
Modelo para relación many-to-many entre tickets y equipos de inventario
"""
from itcj.core.extensions import db


class TicketInventoryItem(db.Model):
    """
    Tabla intermedia para relacionar tickets con múltiples equipos del inventario.
    Un ticket puede afectar a varios equipos (ej: problema en computadoras de un salón).
    Un equipo puede tener múltiples tickets a lo largo del tiempo.
    """
    __tablename__ = "helpdesk_ticket_inventory_items"
    
    id = db.Column(db.Integer, primary_key=True)
    
    ticket_id = db.Column(
        db.Integer,
        db.ForeignKey("helpdesk_ticket.id"),
        nullable=False,
        index=True
    )
    
    inventory_item_id = db.Column(
        db.Integer,
        db.ForeignKey("helpdesk_inventory_items.id"),
        nullable=False,
        index=True
    )
    
    # Timestamp de cuándo se agregó el equipo al ticket
    added_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    
    # Relaciones
    ticket = db.relationship("Ticket", back_populates="ticket_items")
    inventory_item = db.relationship("InventoryItem", back_populates="ticket_items")
    
    # Índices y constraints
    __table_args__ = (
        # Un equipo no puede estar duplicado en el mismo ticket
        db.UniqueConstraint("ticket_id", "inventory_item_id", name="uq_ticket_item"),
        db.Index("ix_ticket_inventory_ticket", "ticket_id"),
        db.Index("ix_ticket_inventory_item", "inventory_item_id"),
    )
    
    def __repr__(self):
        return f"<TicketInventoryItem Ticket:{self.ticket_id} Item:{self.inventory_item_id}>"
    
    def to_dict(self):
        """Serialización para API"""
        return {
            'id': self.id,
            'ticket_id': self.ticket_id,
            'inventory_item_id': self.inventory_item_id,
            'inventory_item': self.inventory_item.to_dict() if self.inventory_item else None,
            'added_at': self.added_at.isoformat() if self.added_at else None,
        }