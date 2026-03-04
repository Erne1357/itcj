"""
Modelo para grupos de equipos (salones, salas, laboratorios)
"""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from itcj2.models.base import Base


class InventoryGroup(Base):
    """
    Grupos o ubicaciones que contienen múltiples equipos.
    Ejemplos: Salón 203, Laboratorio 3, Sala de Maestros, Cubículos Administrativos.
    Cada grupo pertenece a un departamento y tiene capacidades definidas por categoría.
    """
    __tablename__ = "helpdesk_inventory_groups"

    id = Column(Integer, primary_key=True)

    name = Column(String(100), nullable=False)
    code = Column(String(50), unique=True, nullable=False, index=True)

    department_id = Column(Integer, ForeignKey("core_departments.id"), nullable=False, index=True)

    group_type = Column(String(50), default='CLASSROOM')
    # Tipos: CLASSROOM, LABORATORY, OFFICE, MEETING_ROOM, WORKSHOP, OTHER

    description = Column(Text)

    # Ubicación física detallada
    building = Column(String(50))
    floor = Column(String(20))
    location_notes = Column(String(200))

    is_active = Column(Boolean, default=True, nullable=False, index=True)

    # Auditoría
    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relaciones
    department = relationship("Department", backref="inventory_groups")
    created_by = relationship("User", foreign_keys=[created_by_id])

    capacities = relationship(
        "InventoryGroupCapacity",
        back_populates="group",
        cascade="all, delete-orphan",
        lazy='dynamic',
    )

    items = relationship("InventoryItem", back_populates="group", lazy='dynamic')

    __table_args__ = (
        Index("ix_inventory_groups_dept_active", "department_id", "is_active"),
        UniqueConstraint("name", "department_id", name="uq_group_name_per_dept"),
    )

    def __repr__(self):
        return f"<InventoryGroup {self.code}: {self.name}>"

    @property
    def total_capacity(self):
        """Capacidad total sumando todas las categorías"""
        return sum(cap.max_capacity for cap in self.capacities)

    @property
    def total_assigned(self):
        """Total de equipos asignados al grupo"""
        return self.items.filter_by(is_active=True).count()

    @property
    def available_slots(self):
        return self.total_capacity - self.total_assigned

    def get_capacity_for_category(self, category_id):
        capacity = self.capacities.filter_by(category_id=category_id).first()
        return capacity.max_capacity if capacity else 0

    def get_assigned_count_for_category(self, category_id):
        return self.items.filter_by(category_id=category_id, is_active=True).count()

    def get_available_slots_for_category(self, category_id):
        max_cap = self.get_capacity_for_category(category_id)
        assigned = self.get_assigned_count_for_category(category_id)
        return max_cap - assigned

    def to_dict(self, include_items=False, include_capacities=True):
        data = {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'department_id': self.department_id,
            'group_type': self.group_type,
            'description': self.description,
            'building': self.building,
            'floor': self.floor,
            'location_notes': self.location_notes,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'total_capacity': self.total_capacity,
            'total_assigned': self.total_assigned,
            'available_slots': self.available_slots,
            'department': {
                'id': self.department.id,
                'name': self.department.name,
                'code': self.department.code,
            } if self.department else None,
            'created_by': {
                'id': self.created_by.id,
                'full_name': self.created_by.full_name,
            } if self.created_by else None,
        }
        if include_capacities:
            data['capacities'] = [cap.to_dict() for cap in self.capacities]
        if include_items:
            data['items'] = [item.to_dict() for item in self.items.filter_by(is_active=True)]
        return data
