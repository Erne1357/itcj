from sqlalchemy import Column, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from itcj2.models.base import Base


class InventoryGroupCapacity(Base):
    """
    Define la capacidad máxima de equipos por categoría en un grupo.
    Ejemplo: Salón 203 puede tener máximo 30 computadoras, 1 proyector, 0 impresoras.
    """
    __tablename__ = "helpdesk_inventory_group_capacities"

    id = Column(Integer, primary_key=True)

    group_id = Column(Integer, ForeignKey("helpdesk_inventory_groups.id"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("helpdesk_inventory_categories.id"), nullable=False, index=True)

    max_capacity = Column(Integer, nullable=False, default=0)

    # Relaciones
    group = relationship("InventoryGroup", back_populates="capacities")
    category = relationship("InventoryCategory", backref="group_capacities")

    __table_args__ = (
        UniqueConstraint("group_id", "category_id", name="uq_group_category"),
        Index("ix_group_capacities_group", "group_id"),
    )

    def __repr__(self):
        return f"<GroupCapacity Group:{self.group_id} Cat:{self.category_id} Max:{self.max_capacity}>"

    @property
    def current_count(self):
        """Equipos actualmente asignados de esta categoría"""
        return self.group.get_assigned_count_for_category(self.category_id)

    @property
    def available(self):
        return max(0, self.max_capacity - self.current_count)

    @property
    def is_full(self):
        return self.current_count >= self.max_capacity

    @property
    def usage_percentage(self):
        if self.max_capacity == 0:
            return 0
        return (self.current_count / self.max_capacity) * 100

    def to_dict(self):
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
