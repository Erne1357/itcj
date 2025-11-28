"""
Modelo para categorías de inventario (Computadora, Impresora, etc.)
"""
from itcj.core.extensions import db
from datetime import datetime


class InventoryCategory(db.Model):
    """
    Categorías de equipos del inventario.
    Ejemplos: Computadora, Impresora, Proyector, Dispositivo de Red.
    Gestionadas por administradores.
    """
    __tablename__ = "helpdesk_inventory_categories"
    
    # Identificación
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    # Ejemplos: "computer", "printer", "projector", "network_device"
    
    name = db.Column(db.String(100), nullable=False)
    # Ejemplos: "Computadora", "Impresora", "Proyector/Cañón"
    
    description = db.Column(db.Text)
    
    # Configuración
    icon = db.Column(db.String(50), default='fas fa-laptop')
    # Font Awesome icon class
    
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    requires_specs = db.Column(db.Boolean, default=True, nullable=False)
    # Si requiere especificaciones técnicas detalladas
    
    # Campos de especificaciones sugeridos (JSON)
    spec_template = db.Column(db.JSON)
    # Ejemplo para computadora:
    # {
    #     "processor": {"label": "Procesador", "type": "text", "required": true},
    #     "ram": {"label": "RAM (GB)", "type": "number", "required": true},
    #     "storage": {"label": "Almacenamiento", "type": "text", "required": true}
    # }
    
    # Orden de visualización
    display_order = db.Column(db.Integer, default=0)
    
    # Prefijo para número de inventario
    inventory_prefix = db.Column(db.String(10), nullable=False)
    # Ejemplos: "COMP", "IMP", "PROJ"
    
    # Timestamps
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    # Relaciones
    items = db.relationship(
        "InventoryItem",
        back_populates="category",
        lazy='dynamic'
    )
    
    # Índices
    __table_args__ = (
        db.Index("ix_inventory_categories_active_order", "is_active", "display_order"),
    )
    
    def __repr__(self):
        return f"<InventoryCategory {self.code}: {self.name}>"
    
    def to_dict(self):
        """Serialización para API"""
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'icon': self.icon,
            'is_active': self.is_active,
            'requires_specs': self.requires_specs,
            'spec_template': self.spec_template,
            'display_order': self.display_order,
            'inventory_prefix': self.inventory_prefix,
            'items_count': self.items.count() if self.items else 0,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }