"""
Modelo para grupos de equipos (salones, salas, laboratorios)
"""
from itcj.core.extensions import db
from datetime import datetime


class InventoryGroup(db.Model):
    """
    Grupos o ubicaciones que contienen múltiples equipos.
    Ejemplos: Salón 203, Laboratorio 3, Sala de Maestros, Cubículos Administrativos.
    Cada grupo pertenece a un departamento y tiene capacidades definidas por categoría.
    """
    __tablename__ = "helpdesk_inventory_groups"
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Identificación
    name = db.Column(db.String(100), nullable=False)
    # Ejemplos: "Salón 203", "Lab Electrónica", "Sala Maestros"
    
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    # Código único generado: "IND-SALON-203", "CC-LAB-3"
    
    # Departamento al que pertenece
    department_id = db.Column(
        db.Integer,
        db.ForeignKey("core_departments.id"),
        nullable=False,
        index=True
    )
    
    # Tipo de grupo (opcional, para categorizar)
    group_type = db.Column(db.String(50), default='CLASSROOM')
    # Tipos: CLASSROOM, LABORATORY, OFFICE, MEETING_ROOM, WORKSHOP, OTHER
    
    # Descripción
    description = db.Column(db.Text)
    
    # Ubicación física detallada
    building = db.Column(db.String(50))  # Edificio
    floor = db.Column(db.String(20))     # Piso
    location_notes = db.Column(db.String(200))  # Notas adicionales
    
    # Estado
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    
    # Auditoría
    created_by_id = db.Column(db.BigInteger, db.ForeignKey("core_users.id"), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    
    # Relaciones
    department = db.relationship("Department", backref="inventory_groups")
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    
    # Capacidades del grupo (por categoría)
    capacities = db.relationship(
        "InventoryGroupCapacity",
        back_populates="group",
        cascade="all, delete-orphan",
        lazy='dynamic'
    )
    
    # Equipos asignados a este grupo
    items = db.relationship(
        "InventoryItem",
        back_populates="group",
        lazy='dynamic'
    )
    
    # Índices
    __table_args__ = (
        db.Index("ix_inventory_groups_dept_active", "department_id", "is_active"),
        # Permitir mismo nombre en diferentes departamentos
        db.UniqueConstraint("name", "department_id", name="uq_group_name_per_dept"),
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
        """Espacios disponibles en el grupo"""
        return self.total_capacity - self.total_assigned
    
    def get_capacity_for_category(self, category_id):
        """Obtiene la capacidad máxima para una categoría específica"""
        capacity = self.capacities.filter_by(category_id=category_id).first()
        return capacity.max_capacity if capacity else 0
    
    def get_assigned_count_for_category(self, category_id):
        """Cuenta equipos asignados de una categoría específica"""
        return self.items.filter_by(
            category_id=category_id,
            is_active=True
        ).count()
    
    def get_available_slots_for_category(self, category_id):
        """Espacios disponibles para una categoría específica"""
        max_cap = self.get_capacity_for_category(category_id)
        assigned = self.get_assigned_count_for_category(category_id)
        return max_cap - assigned
    
    def to_dict(self, include_items=False, include_capacities=True):
        """Serialización para API"""
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
                'code': self.department.code
            } if self.department else None,
            'created_by': {
                'id': self.created_by.id,
                'full_name': self.created_by.full_name
            } if self.created_by else None,
        }
        
        if include_capacities:
            data['capacities'] = [cap.to_dict() for cap in self.capacities]
        
        if include_items:
            data['items'] = [item.to_dict() for item in self.items.filter_by(is_active=True)]
        
        return data