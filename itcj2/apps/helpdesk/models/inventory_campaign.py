"""
Modelo de Campaña de Inventario.

Una campaña agrupa todos los equipos registrados por el Centro de Cómputo
para un departamento en un periodo dado. El flujo es:

  CC crea campaña (OPEN)
    → registra items con campaign_id = esta campaña
    → cierra campaña (PENDING_VALIDATION)
      → Jefe de Dpto valida (VALIDATED) o rechaza (REJECTED)
        → Si rechaza, CC puede reabrir (OPEN) y corregir
"""
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey,
    Index, Integer, JSON, String, Text,
)
from sqlalchemy.orm import relationship, backref
from sqlalchemy.sql import func

from itcj2.models.base import Base


class InventoryCampaign(Base):
    __tablename__ = 'helpdesk_inventory_campaigns'

    id = Column(BigInteger, primary_key=True)

    # Folio único: CAM-{YEAR}-{SEQ:03d}
    folio = Column(String(20), unique=True, nullable=False)

    department_id = Column(Integer, ForeignKey('core_departments.id'), nullable=False, index=True)
    academic_period_id = Column(Integer, ForeignKey('core_academic_periods.id'), nullable=True, index=True)

    # OPEN | PENDING_VALIDATION | VALIDATED | REJECTED
    status = Column(String(25), nullable=False, default='OPEN', index=True)

    title = Column(String(200), nullable=False)
    notes = Column(Text, nullable=True)

    # Ciclo de vida
    started_at = Column(DateTime, nullable=False, server_default=func.now())
    closed_at = Column(DateTime, nullable=True)      # cuando CC cierra para validación
    validated_at = Column(DateTime, nullable=True)   # cuando jefe aprueba/rechaza

    # Usuarios
    created_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)
    closed_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)
    validated_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)

    # Resultado de validación
    validation_notes = Column(Text, nullable=True)   # observaciones del jefe al aprobar
    rejection_reason = Column(Text, nullable=True)   # motivo de rechazo

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=True, onupdate=func.now())

    # ------------------------------------------------------------------
    # Relaciones
    # ------------------------------------------------------------------
    department = relationship('Department', foreign_keys=[department_id])
    academic_period = relationship('AcademicPeriod', foreign_keys=[academic_period_id])

    created_by = relationship('User', foreign_keys=[created_by_id])
    closed_by = relationship('User', foreign_keys=[closed_by_id])
    validated_by = relationship('User', foreign_keys=[validated_by_id])

    items = relationship(
        'InventoryItem',
        foreign_keys='InventoryItem.campaign_id',
        back_populates='campaign',
        lazy='dynamic',
    )

    validation_history = relationship(
        'InventoryCampaignValidation',
        back_populates='campaign',
        cascade='all, delete-orphan',
        order_by='desc(InventoryCampaignValidation.performed_at)',
    )

    __table_args__ = (
        Index('ix_inv_campaigns_dept_status', 'department_id', 'status'),
    )

    # ------------------------------------------------------------------
    # Propiedades de conveniencia
    # ------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self.status == 'OPEN'

    @property
    def is_pending_validation(self) -> bool:
        return self.status == 'PENDING_VALIDATION'

    @property
    def is_validated(self) -> bool:
        return self.status == 'VALIDATED'

    @property
    def is_rejected(self) -> bool:
        return self.status == 'REJECTED'

    @property
    def items_count(self) -> int:
        return self.items.count() if self.items is not None else 0

    def to_dict(self, include_relations: bool = False) -> dict:
        def _iso(val):
            return val.isoformat() if val and hasattr(val, 'isoformat') else val

        data = {
            'id': self.id,
            'folio': self.folio,
            'department_id': self.department_id,
            'academic_period_id': self.academic_period_id,
            'status': self.status,
            'title': self.title,
            'notes': self.notes,
            'started_at': _iso(self.started_at),
            'closed_at': _iso(self.closed_at),
            'validated_at': _iso(self.validated_at),
            'created_by_id': self.created_by_id,
            'closed_by_id': self.closed_by_id,
            'validated_by_id': self.validated_by_id,
            'validation_notes': self.validation_notes,
            'rejection_reason': self.rejection_reason,
            'created_at': _iso(self.created_at),
            'updated_at': _iso(self.updated_at),
            'is_open': self.is_open,
            'is_pending_validation': self.is_pending_validation,
            'is_validated': self.is_validated,
            'is_rejected': self.is_rejected,
            'items_count': self.items_count,
        }

        if include_relations:
            data['department'] = {
                'id': self.department.id,
                'name': self.department.name,
                'code': self.department.code,
            } if self.department else None
            data['academic_period'] = {
                'id': self.academic_period.id,
                'name': self.academic_period.name,
                'code': self.academic_period.code,
            } if self.academic_period else None
            data['created_by'] = {
                'id': self.created_by.id,
                'full_name': self.created_by.full_name,
            } if self.created_by else None
            data['validated_by'] = {
                'id': self.validated_by.id,
                'full_name': self.validated_by.full_name,
            } if self.validated_by else None

        return data

    def __repr__(self):
        return f'<InventoryCampaign {self.folio} [{self.status}]>'
