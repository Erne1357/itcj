"""
Registro formal de cada acción de aprobación o rechazo sobre una campaña.

Cada vez que un Jefe de Departamento aprueba o rechaza una campaña se
inserta un registro aquí, incluyendo un snapshot de los items en ese momento.
"""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from itcj2.models.base import Base


class InventoryCampaignValidation(Base):
    __tablename__ = 'helpdesk_inventory_campaign_validations'

    id = Column(BigInteger, primary_key=True)

    campaign_id = Column(
        BigInteger,
        ForeignKey('helpdesk_inventory_campaigns.id'),
        nullable=False,
        index=True,
    )

    # APPROVED | REJECTED
    action = Column(String(10), nullable=False)

    performed_by_id = Column(
        BigInteger,
        ForeignKey('core_users.id'),
        nullable=False,
        index=True,
    )
    performed_at = Column(DateTime, nullable=False, server_default=func.now())

    notes = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)

    # Snapshot de los items en el momento de validar:
    # {
    #   "total": 45,
    #   "new_items": [id1, id2, ...],       <- en esta campaña
    #   "existing_items": [id3, id4, ...],  <- pre-existentes en el dpto
    # }
    items_snapshot = Column(JSON, nullable=True)

    # ------------------------------------------------------------------
    # Relaciones
    # ------------------------------------------------------------------
    campaign = relationship(
        'InventoryCampaign',
        back_populates='validation_history',
    )
    performed_by = relationship('User', foreign_keys=[performed_by_id])

    def to_dict(self) -> dict:
        def _iso(val):
            return val.isoformat() if val and hasattr(val, 'isoformat') else val

        return {
            'id': self.id,
            'campaign_id': self.campaign_id,
            'action': self.action,
            'performed_by_id': self.performed_by_id,
            'performed_at': _iso(self.performed_at),
            'notes': self.notes,
            'ip_address': self.ip_address,
            'items_snapshot': self.items_snapshot,
            'performed_by': {
                'id': self.performed_by.id,
                'full_name': self.performed_by.full_name,
            } if self.performed_by else None,
        }

    def __repr__(self):
        return f'<InventoryCampaignValidation campaign={self.campaign_id} action={self.action}>'
