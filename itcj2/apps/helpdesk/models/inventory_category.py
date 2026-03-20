from sqlalchemy import Boolean, Column, DateTime, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from itcj2.models.base import Base


class InventoryCategory(Base):
    """
    Categorías de equipos del inventario.
    Ejemplos: Computadora, Impresora, Proyector, Dispositivo de Red.
    Gestionadas por administradores.
    """
    __tablename__ = "helpdesk_inventory_categories"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)

    # Configuración
    icon = Column(String(50), default='fas fa-laptop')
    is_active = Column(Boolean, default=True, nullable=False)
    requires_specs = Column(Boolean, default=True, nullable=False)

    # Campos de especificaciones sugeridos (JSON)
    spec_template = Column(JSON)

    display_order = Column(Integer, default=0)

    # Prefijo para número de inventario (ej: "COMP", "IMP", "PROJ")
    inventory_prefix = Column(String(10), nullable=False)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relaciones
    items = relationship("InventoryItem", back_populates="category", lazy='dynamic')

    __table_args__ = (
        Index("ix_inventory_categories_active_order", "is_active", "display_order"),
    )

    def __repr__(self):
        return f"<InventoryCategory {self.code}: {self.name}>"

    def to_dict(self):
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
