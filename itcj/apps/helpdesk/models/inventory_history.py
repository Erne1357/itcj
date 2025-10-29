"""
Modelo para historial de cambios en equipos del inventario
"""
from itcj.core.extensions import db
from datetime import datetime


class InventoryHistory(db.Model):
    """
    Registro de todos los cambios en equipos del inventario.
    Proporciona trazabilidad completa: quién, cuándo, qué cambió y por qué.
    """
    __tablename__ = "helpdesk_inventory_history"
    
    id = db.Column(db.Integer, primary_key=True)
    
    item_id = db.Column(
        db.Integer,
        db.ForeignKey("helpdesk_inventory_items.id"),
        nullable=False,
        index=True
    )
    
    # Tipo de evento
    event_type = db.Column(db.String(50), nullable=False, index=True)
    # Eventos posibles:
    # - REGISTERED: Equipo registrado inicialmente
    # - ASSIGNED_TO_DEPT: Asignado al departamento (global)
    # - ASSIGNED_TO_USER: Asignado a usuario específico
    # - UNASSIGNED: Liberado de usuario (vuelta a global)
    # - REASSIGNED: Reasignado a otro usuario
    # - LOCATION_CHANGED: Cambio de ubicación
    # - STATUS_CHANGED: Cambio de estado (ACTIVE, MAINTENANCE, etc.)
    # - MAINTENANCE_SCHEDULED: Mantenimiento programado
    # - MAINTENANCE_COMPLETED: Mantenimiento completado
    # - SPECS_UPDATED: Especificaciones actualizadas
    # - TRANSFERRED: Transferido a otro departamento
    # - DEACTIVATED: Dado de baja
    # - REACTIVATED: Reactivado después de baja
    
    # Datos del cambio (JSON flexible)
    old_value = db.Column(db.JSON)
    # Estado anterior del campo modificado
    # Ejemplo para asignación:
    # {"assigned_to_user_id": null, "assigned_to_user_name": null}
    
    new_value = db.Column(db.JSON)
    # Estado nuevo del campo modificado
    # Ejemplo:
    # {"assigned_to_user_id": 123, "assigned_to_user_name": "Juan Pérez"}
    
    # Contexto y observaciones
    notes = db.Column(db.Text)
    # Razón del cambio, observaciones adicionales
    
    # Relación con ticket (si aplica)
    related_ticket_id = db.Column(
        db.Integer,
        db.ForeignKey("helpdesk_ticket.id"),
        nullable=True
    )
    
    # Auditoría
    performed_by_id = db.Column(
        db.BigInteger,
        db.ForeignKey("core_users.id"),
        nullable=False
    )
    
    timestamp = db.Column(
        db.DateTime,
        server_default=db.func.now(),
        nullable=False,
        index=True
    )
    
    ip_address = db.Column(db.String(50))
    # IP desde donde se realizó el cambio
    
    # Relaciones
    item = db.relationship("InventoryItem", back_populates="history")
    
    performed_by = db.relationship("User", backref="inventory_actions")
    
    related_ticket = db.relationship("Ticket", backref="inventory_history_entries")
    
    # Índices compuestos
    __table_args__ = (
        db.Index("ix_inventory_history_item_timestamp", "item_id", "timestamp"),
        db.Index("ix_inventory_history_event_timestamp", "event_type", "timestamp"),
    )
    
    def __repr__(self):
        return f"<InventoryHistory {self.event_type} on item {self.item_id} at {self.timestamp}>"
    
    def to_dict(self, include_relations=False):
        """Serialización para API"""
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
                'email': self.performed_by.email
            } if self.performed_by else None
            
            data['related_ticket'] = {
                'id': self.related_ticket.id,
                'ticket_number': self.related_ticket.ticket_number,
                'title': self.related_ticket.title
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