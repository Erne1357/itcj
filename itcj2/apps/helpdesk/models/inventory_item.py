"""
Modelo para equipos individuales del inventario
"""
from datetime import date

from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import backref, relationship, object_session
from sqlalchemy.sql import func

from itcj2.models.base import Base


class InventoryItem(Base):
    """
    Equipos específicos del inventario institucional.
    Registrados por Admin, asignados por Jefe de Departamento.
    """
    __tablename__ = "helpdesk_inventory_items"

    id = Column(Integer, primary_key=True)

    inventory_number = Column(String(50), unique=True, nullable=False, index=True)

    category_id = Column(Integer, ForeignKey("helpdesk_inventory_categories.id"), nullable=False, index=True)

    brand = Column(String(100))
    model = Column(String(100))
    supplier_serial = Column(String(150), unique=True, index=True)
    itcj_serial = Column(String(150), unique=True, index=True)
    id_tecnm = Column(String(100), unique=True, index=True)

    specifications = Column(JSON)

    department_id = Column(Integer, ForeignKey("core_departments.id"), nullable=False, index=True)

    assigned_to_user_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True, index=True)

    location_detail = Column(String(200))

    group_id = Column(Integer, ForeignKey("helpdesk_inventory_groups.id"), nullable=True, index=True)

    status = Column(String(30), nullable=False, default='PENDING_ASSIGNMENT', index=True)

    # Fechas importantes
    acquisition_date = Column(Date)
    warranty_expiration = Column(Date)
    last_maintenance_date = Column(Date)

    maintenance_frequency_days = Column(Integer)
    next_maintenance_date = Column(Date)

    notes = Column(Text)

    # Auditoría de registro
    registered_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False)
    registered_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Auditoría de asignación
    assigned_by_id = Column(BigInteger, ForeignKey("core_users.id"))
    assigned_at = Column(DateTime)

    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Soft delete
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    deactivated_at = Column(DateTime)
    deactivated_by_id = Column(BigInteger, ForeignKey("core_users.id"))
    deactivation_reason = Column(Text)

    # Última verificación física
    last_verified_at = Column(DateTime, nullable=True)
    last_verified_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)

    # ------------------------------------------------------------------
    # Versionado (cadena lineal de sucesión entre equipos)
    # ------------------------------------------------------------------
    predecessor_item_id = Column(
        BigInteger,
        ForeignKey("helpdesk_inventory_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ------------------------------------------------------------------
    # Campaña de inventario
    # ------------------------------------------------------------------
    campaign_id = Column(
        BigInteger,
        ForeignKey("helpdesk_inventory_campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ------------------------------------------------------------------
    # Bloqueo tras validación
    # ------------------------------------------------------------------
    is_locked = Column(Boolean, nullable=False, default=False)
    validated_at = Column(DateTime, nullable=True)
    validated_by_id = Column(
        BigInteger,
        ForeignKey("core_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    locked_campaign_id = Column(
        BigInteger,
        ForeignKey("helpdesk_inventory_campaigns.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relaciones
    category = relationship("InventoryCategory", back_populates="items")
    department = relationship("Department", backref="inventory_items")
    group = relationship("InventoryGroup", back_populates="items")

    assigned_to_user = relationship("User", foreign_keys=[assigned_to_user_id], backref="assigned_equipment")
    registered_by = relationship("User", foreign_keys=[registered_by_id], backref="registered_equipment")
    assigned_by = relationship("User", foreign_keys=[assigned_by_id])
    deactivated_by = relationship("User", foreign_keys=[deactivated_by_id])
    last_verified_by = relationship("User", foreign_keys=[last_verified_by_id])
    validated_by = relationship("User", foreign_keys=[validated_by_id])

    # Versionado: predecesor y sucesor (cadena lineal)
    predecessor = relationship(
        "InventoryItem",
        foreign_keys=[predecessor_item_id],
        remote_side="InventoryItem.id",
        backref=backref("successor", uselist=False),
    )

    # Campaña de inventario a la que pertenece este item
    campaign = relationship(
        "InventoryCampaign",
        foreign_keys=[campaign_id],
        back_populates="items",
    )

    verifications = relationship(
        "InventoryVerification",
        back_populates="inventory_item",
        cascade="all, delete-orphan",
        lazy="dynamic",
        order_by="desc(InventoryVerification.verified_at)",
    )

    ticket_items = relationship(
        "TicketInventoryItem",
        back_populates="inventory_item",
        cascade="all, delete-orphan",
        lazy='dynamic',
    )

    history = relationship(
        "InventoryHistory",
        back_populates="item",
        cascade="all, delete-orphan",
        lazy='dynamic',
    )

    __table_args__ = (
        Index("ix_inventory_items_dept_active", "department_id", "is_active"),
        Index("ix_inventory_items_user_active", "assigned_to_user_id", "is_active"),
        Index("ix_inventory_items_status_active", "status", "is_active"),
        Index("ix_inventory_items_category", "category_id", "is_active"),
        Index("ix_inventory_items_campaign_locked", "campaign_id", "is_locked"),
    )

    def __repr__(self):
        return f"<InventoryItem {self.inventory_number}: {self.brand} {self.model}>"

    @property
    def is_assigned_to_user(self):
        return self.assigned_to_user_id is not None

    @property
    def is_in_group(self):
        return self.group_id is not None

    @property
    def is_global(self):
        return self.assigned_to_user_id is None and not self.is_in_group

    @property
    def is_pending_assignment(self):
        return self.status == 'PENDING_ASSIGNMENT'

    @property
    def display_name(self):
        parts = [self.inventory_number]
        if self.brand:
            parts.append(self.brand)
        if self.model:
            parts.append(self.model)
        return " - ".join(parts)

    @property
    def is_under_warranty(self):
        if not self.warranty_expiration:
            return False
        return self.warranty_expiration >= date.today()

    @property
    def warranty_days_remaining(self):
        if not self.is_under_warranty:
            return 0
        return (self.warranty_expiration - date.today()).days

    @property
    def has_predecessor(self) -> bool:
        return self.predecessor_item_id is not None

    @property
    def is_latest_version(self) -> bool:
        """True si no tiene sucesor (es la versión más reciente de la cadena)."""
        return self.successor is None

    @property
    def version_chain(self) -> list:
        """Retorna la cadena completa desde el primer item hasta el actual."""
        chain = [self]
        current = self
        while current.predecessor:
            chain.insert(0, current.predecessor)
            current = current.predecessor
        return chain

    @property
    def needs_maintenance(self):
        if not self.next_maintenance_date:
            return False
        return self.next_maintenance_date <= date.today()

    @property
    def tickets_count(self):
        """Total de tickets relacionados"""
        return self.ticket_items.count() if self.ticket_items is not None else 0

    @property
    def active_tickets_count(self):
        """Tickets activos (no cerrados ni cancelados)"""
        from itcj2.apps.helpdesk.models.ticket import Ticket
        db = object_session(self)
        if db is None:
            return 0
        active_ticket_ids = [ti.ticket_id for ti in self.ticket_items]
        if not active_ticket_ids:
            return 0
        return db.query(Ticket).filter(
            Ticket.id.in_(active_ticket_ids),
            ~Ticket.status.in_(['CLOSED', 'CANCELED']),
        ).count()

    @property
    def tickets(self):
        """Obtener tickets relacionados a través de la tabla intermedia"""
        from itcj2.apps.helpdesk.models.ticket import Ticket
        db = object_session(self)
        if db is None:
            return []
        ticket_ids = [ti.ticket_id for ti in self.ticket_items]
        if not ticket_ids:
            return []
        return db.query(Ticket).filter(Ticket.id.in_(ticket_ids)).all()

    def to_dict(self, include_relations=False):
        def _date_iso(val):
            if val is None:
                return None
            if hasattr(val, 'isoformat'):
                return val.isoformat()
            return str(val)

        data = {
            'id': self.id,
            'inventory_number': self.inventory_number,
            'category_id': self.category_id,
            'brand': self.brand,
            'model': self.model,
            'supplier_serial': self.supplier_serial,
            'itcj_serial': self.itcj_serial,
            'id_tecnm': self.id_tecnm,
            'specifications': self.specifications,
            'department_id': self.department_id,
            'assigned_to_user_id': self.assigned_to_user_id,
            'group_id': self.group_id,
            'location_detail': self.location_detail,
            'status': self.status,
            'acquisition_date': self.acquisition_date.isoformat() if self.acquisition_date else None,
            'warranty_expiration': self.warranty_expiration.isoformat() if self.warranty_expiration else None,
            'last_maintenance_date': self.last_maintenance_date.isoformat() if self.last_maintenance_date else None,
            'maintenance_frequency_days': self.maintenance_frequency_days,
            'next_maintenance_date': self.next_maintenance_date.isoformat() if self.next_maintenance_date else None,
            'notes': self.notes,
            'registered_at': _date_iso(self.registered_at),
            'assigned_by': self.assigned_by.to_dict() if self.assigned_by else None,
            'assigned_at': _date_iso(self.assigned_at),
            'updated_at': _date_iso(self.updated_at),
            'created_at': _date_iso(self.created_at),
            'is_active': self.is_active,
            'display_name': self.display_name,
            'is_assigned_to_user': self.is_assigned_to_user,
            'is_global': self.is_global,
            'is_in_group': self.is_in_group,
            'is_pending_assignment': self.is_pending_assignment,
            'is_under_warranty': self.is_under_warranty,
            'warranty_days_remaining': self.warranty_days_remaining if self.is_under_warranty else 0,
            'needs_maintenance': self.needs_maintenance,
            'tickets_count': self.tickets_count,
            'active_tickets_count': self.active_tickets_count,
            # Verificación física
            'last_verified_at': _date_iso(self.last_verified_at),
            'last_verified_by_id': self.last_verified_by_id,
            # Versionado
            'predecessor_item_id': self.predecessor_item_id,
            'has_predecessor': self.has_predecessor,
            'is_latest_version': self.is_latest_version,
            # Campaña
            'campaign_id': self.campaign_id,
            # Bloqueo
            'is_locked': self.is_locked,
            'validated_at': _date_iso(self.validated_at),
            'validated_by_id': self.validated_by_id,
            'locked_campaign_id': self.locked_campaign_id,
        }

        if include_relations:
            data['category'] = self.category.to_dict() if self.category else None
            data['department'] = {
                'id': self.department.id,
                'name': self.department.name,
                'code': self.department.code,
            } if self.department else None
            data['assigned_to_user'] = {
                'id': self.assigned_to_user.id,
                'full_name': self.assigned_to_user.full_name,
                'email': self.assigned_to_user.email,
            } if self.assigned_to_user else None
            data['registered_by'] = {
                'id': self.registered_by.id,
                'full_name': self.registered_by.full_name,
            } if self.registered_by else None
            data['group'] = self.group.to_dict() if self.group else None
            data['last_verified_by'] = {
                'id': self.last_verified_by.id,
                'full_name': self.last_verified_by.full_name,
            } if self.last_verified_by else None

        return data
