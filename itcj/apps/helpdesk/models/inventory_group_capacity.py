"""
Modelo para capacidades de equipos por categoría en cada grupo
"""
from itcj.core.extensions import db


class InventoryGroupCapacity(db.Model):
    """
    Define la capacidad máxima de equipos por categoría en un grupo.
    Ejemplo: Salón 203 puede tener máximo 30 computadoras, 1 proyector, 0 impresoras.
    """
    __tablename__ = "helpdesk_inventory_group_capacities"
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Grupo al que pertenece
    group_id = db.Column(
        db.Integer,
        db.ForeignKey("helpdesk_inventory_groups.id"),
        nullable=False,
        index=True
    )
    
    # Categoría de equipo
    category_id = db.Column(
        db.Integer,
        db.ForeignKey("helpdesk_inventory_categories.id"),
        nullable=False,
        index=True
    )
    
    # Capacidad máxima
    max_capacity = db.Column(db.Integer, nullable=False, default=0)
    # Número máximo de equipos de esta categoría que puede contener el grupo
    
    # Relaciones
    group = db.relationship("InventoryGroup", back_populates="capacities")
    category = db.relationship("InventoryCategory", backref="group_capacities")
    
    # Índices y constraints
    __table_args__ = (
        # Un grupo solo puede tener una capacidad definida por categoría
        db.UniqueConstraint("group_id", "category_id", name="uq_group_category"),
        db.Index("ix_group_capacities_group", "group_id"),
    )
    
    def __repr__(self):
        return f"<GroupCapacity Group:{self.group_id} Cat:{self.category_id} Max:{self.max_capacity}>"
    
    @property
    def current_count(self):
        """Equipos actualmente asignados de esta categoría"""
        return self.group.get_assigned_count_for_category(self.category_id)
    
    @property
    def available(self):
        """Espacios disponibles"""
        return max(0, self.max_capacity - self.current_count)
    
    @property
    def is_full(self):
        """¿Está lleno?"""
        return self.current_count >= self.max_capacity
    
    @property
    def usage_percentage(self):
        """Porcentaje de ocupación"""
        if self.max_capacity == 0:
            return 0
        return (self.current_count / self.max_capacity) * 100
    
    def to_dict(self):
        """Serialización para API"""
        return {
            'id': self.id,
            'group_id': self.group_id,
            'category_id': self.category_id,
            'category': self.category.to_dict() if self.category else None,
            'max_capacity': self.max_capacity,
            'current_count': self.current_count,
            'available': self.available,
            'is_full': self.is_full,
            'usage_percentage': round(self.usage_percentage, 1),
        }