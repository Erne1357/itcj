"""
Modelo para equipos individuales del inventario
"""
from itcj.core.extensions import db
from datetime import datetime, date


class InventoryItem(db.Model):
    """
    Equipos específicos del inventario institucional.
    Registrados por Admin, asignados por Jefe de Departamento.
    """
    __tablename__ = "helpdesk_inventory_items"
    
    # Identificación única
    id = db.Column(db.Integer, primary_key=True)
    
    inventory_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    # Formato: "COMP-2025-001", "IMP-2025-045"
    
    # Categoría
    category_id = db.Column(
        db.Integer,
        db.ForeignKey("helpdesk_inventory_categories.id"),
        nullable=False,
        index=True
    )
    
    # Información básica del equipo
    brand = db.Column(db.String(100))
    # Marca: HP, Dell, Lenovo, Canon, Epson, etc.
    
    model = db.Column(db.String(100))
    # Modelo: OptiPlex 7090, Vostro 3681, etc.
    
    serial_number = db.Column(db.String(100), unique=True, index=True)
    # Número de serie del fabricante
    
    # Especificaciones técnicas (JSON flexible)
    specifications = db.Column(db.JSON)
    # Ejemplos:
    # Computadora: {
    #     "processor": "Intel Core i5-11500",
    #     "ram": "16",
    #     "ram_unit": "GB",
    #     "storage": "512",
    #     "storage_unit": "GB",
    #     "storage_type": "SSD",
    #     "os": "Windows 11 Pro",
    #     "has_monitor": true,
    #     "monitor_size": "24"
    # }
    # Impresora: {
    #     "type": "Láser",
    #     "color": true,
    #     "network": true,
    #     "duplex": true
    # }
    
    # Ubicación y asignación
    department_id = db.Column(
        db.Integer,
        db.ForeignKey("core_departments.id"),
        nullable=False,
        index=True
    )
    
    assigned_to_user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("core_users.id"),
        nullable=True,
        index=True
    )
    # NULL = asignado al departamento (global)
    # NOT NULL = asignado a usuario específico
    
    location_detail = db.Column(db.String(200))
    # Ubicación específica: "Aula 201", "Lab 3 - Estación 5", "Oficina del Director"
    
    # Grupo al que pertenece (salón, laboratorio, etc.)
    group_id = db.Column(
        db.Integer,
        db.ForeignKey("helpdesk_inventory_groups.id"),
        nullable=True,
        index=True
    )
    # NULL = no asignado a grupo específico
    # NOT NULL = asignado a un grupo/salón

    # Estado del equipo
    status = db.Column(db.String(30), nullable=False, default='PENDING_ASSIGNMENT', index=True)
    # Estados: 
    # - PENDING_ASSIGNMENT: Recién registrado, en limbo del CC
    # - ACTIVE: Activo y en uso
    # - MAINTENANCE: En mantenimiento
    # - DAMAGED: Dañado
    # - RETIRED: Dado de baja
    # - LOST: Extraviado
    
    # Fechas importantes
    acquisition_date = db.Column(db.Date)
    warranty_expiration = db.Column(db.Date)
    last_maintenance_date = db.Column(db.Date)
    
    # Mantenimiento preventivo (opcional)
    maintenance_frequency_days = db.Column(db.Integer)
    # Cada cuántos días requiere mantenimiento preventivo
    
    next_maintenance_date = db.Column(db.Date)
    # Calculado automáticamente
    
    # Observaciones generales
    notes = db.Column(db.Text)
    
    # Auditoría de registro
    registered_by_id = db.Column(
        db.BigInteger,
        db.ForeignKey("core_users.id"),
        nullable=False
    )
    registered_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    
    # Auditoría de asignación
    assigned_by_id = db.Column(db.BigInteger, db.ForeignKey("core_users.id"))
    assigned_at = db.Column(db.DateTime)
    
    # Timestamps generales
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.now(),
        onupdate=db.func.now()
    )
    
    # Soft delete
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    deactivated_at = db.Column(db.DateTime)
    deactivated_by_id = db.Column(db.BigInteger, db.ForeignKey("core_users.id"))
    deactivation_reason = db.Column(db.Text)
    
    # Relaciones
    category = db.relationship("InventoryCategory", back_populates="items")
    
    department = db.relationship("Department", backref="inventory_items")
    
    group = db.relationship("InventoryGroup", back_populates="items")

    assigned_to_user = db.relationship(
        "User",
        foreign_keys=[assigned_to_user_id],
        backref="assigned_equipment"
    )
    
    registered_by = db.relationship(
        "User",
        foreign_keys=[registered_by_id],
        backref="registered_equipment"
    )
    
    assigned_by = db.relationship(
        "User",
        foreign_keys=[assigned_by_id]
    )
    
    deactivated_by = db.relationship(
        "User",
        foreign_keys=[deactivated_by_id]
    )
    
    # Relación con tickets
    tickets = db.relationship(
        "Ticket",
        back_populates="inventory_item",
        lazy='dynamic'
    )

    ticket_items = db.relationship(
        "TicketInventoryItem",
        back_populates="inventory_item",
        cascade="all, delete-orphan",
        lazy='dynamic'
    )
    
    # Historial de cambios
    history = db.relationship(
        "InventoryHistory",
        back_populates="item",
        cascade="all, delete-orphan",
        lazy='dynamic'
    )
    
    # Índices compuestos
    __table_args__ = (
        db.Index("ix_inventory_items_dept_active", "department_id", "is_active"),
        db.Index("ix_inventory_items_user_active", "assigned_to_user_id", "is_active"),
        db.Index("ix_inventory_items_status_active", "status", "is_active"),
        db.Index("ix_inventory_items_category", "category_id", "is_active"),
    )
    
    def __repr__(self):
        return f"<InventoryItem {self.inventory_number}: {self.brand} {self.model}>"
    
    # Propiedades calculadas
    @property
    def is_assigned_to_user(self):
        """¿Está asignado a un usuario específico?"""
        return self.assigned_to_user_id is not None
    
    @property
    def is_global(self):
        """¿Es global del departamento?"""
        return self.assigned_to_user_id is None
    
    @property
    def display_name(self):
        """Nombre legible para mostrar en UI"""
        parts = [self.inventory_number]
        if self.brand:
            parts.append(self.brand)
        if self.model:
            parts.append(self.model)
        return " - ".join(parts)
    
    @property
    def is_under_warranty(self):
        """¿Tiene garantía vigente?"""
        if not self.warranty_expiration:
            return False
        return self.warranty_expiration >= date.today()
    
    @property
    def warranty_days_remaining(self):
        """Días restantes de garantía"""
        if not self.is_under_warranty:
            return 0
        delta = self.warranty_expiration - date.today()
        return delta.days
    
    @property
    def needs_maintenance(self):
        """¿Necesita mantenimiento preventivo?"""
        if not self.next_maintenance_date:
            return False
        return self.next_maintenance_date <= date.today()
    
    @property
    def tickets_count(self):
        """Total de tickets relacionados"""
        return self.tickets.count() if self.tickets else 0
    
    @property
    def active_tickets_count(self):
        """Tickets activos (no cerrados ni cancelados)"""
        if not self.tickets:
            return 0
        from itcj.apps.helpdesk.models.ticket import Ticket
        return self.tickets.filter(
            ~Ticket.status.in_(['CLOSED', 'CANCELED'])
        ).count()
    
    @property
    def is_in_group(self):
        """¿Está asignado a un grupo/salón?"""
        return self.group_id is not None
    
    @property
    def is_pending_assignment(self):
        """¿Está en espera de asignación?"""
        return self.status == 'PENDING_ASSIGNMENT'
    
    @property
    def tickets_count(self):
        """Total de tickets relacionados"""
        return self.ticket_items.count() if self.ticket_items else 0
    
    @property
    def active_tickets_count(self):
        """Tickets activos (no cerrados ni cancelados)"""
        if not self.ticket_items:
            return 0
        from itcj.apps.helpdesk.models.ticket import Ticket
        active_ticket_ids = [
            ti.ticket_id for ti in self.ticket_items
        ]
        if not active_ticket_ids:
            return 0
        return Ticket.query.filter(
            Ticket.id.in_(active_ticket_ids),
            ~Ticket.status.in_(['CLOSED', 'CANCELED'])
        ).count()

    def to_dict(self, include_relations=False):
        """Serialización para API"""
        data = {
            'id': self.id,
            'inventory_number': self.inventory_number,
            'category_id': self.category_id,
            'brand': self.brand,
            'model': self.model,
            'serial_number': self.serial_number,
            'specifications': self.specifications,
            'department_id': self.department_id,
            'assigned_to_user_id': self.assigned_to_user_id,
            'group_id': self.group_id,  # NUEVO
            'location_detail': self.location_detail,
            'status': self.status,
            'acquisition_date': self.acquisition_date.isoformat() if self.acquisition_date else None,
            'warranty_expiration': self.warranty_expiration.isoformat() if self.warranty_expiration else None,
            'last_maintenance_date': self.last_maintenance_date.isoformat() if self.last_maintenance_date else None,
            'maintenance_frequency_days': self.maintenance_frequency_days,
            'next_maintenance_date': self.next_maintenance_date.isoformat() if self.next_maintenance_date else None,
            'notes': self.notes,
            'registered_at': self.registered_at.isoformat() if self.registered_at else None,
            'assigned_by': self.assigned_by.to_dict() if self.assigned_by else None,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'is_active': self.is_active,
            # Propiedades calculadas
            'display_name': self.display_name,
            'is_assigned_to_user': self.is_assigned_to_user,
            'is_global': self.is_global,
            'is_in_group': self.is_in_group,  # NUEVO
            'is_pending_assignment': self.is_pending_assignment,  # NUEVO
            'is_under_warranty': self.is_under_warranty,
            'warranty_days_remaining': self.warranty_days_remaining if self.is_under_warranty else 0,
            'needs_maintenance': self.needs_maintenance,
            'tickets_count': self.tickets_count,
            'active_tickets_count': self.active_tickets_count,
        }
        
        if include_relations:
            data['category'] = self.category.to_dict() if self.category else None
            data['department'] = {
                'id': self.department.id,
                'name': self.department.name,
                'code': self.department.code  # AGREGADO
            } if self.department else None
            data['assigned_to_user'] = {
                'id': self.assigned_to_user.id,
                'full_name': self.assigned_to_user.full_name,
                'email': self.assigned_to_user.email
            } if self.assigned_to_user else None
            data['registered_by'] = {
                'id': self.registered_by.id,
                'full_name': self.registered_by.full_name
            } if self.registered_by else None
            data['group'] = self.group.to_dict() if self.group else None  # NUEVO
        
        return data