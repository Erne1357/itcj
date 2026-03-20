from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class VTDonation(Base):
    """Registro de donaciones de ropa o despensa."""
    __tablename__ = 'vistetec_donations'

    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False, index=True)

    donor_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)
    donor_name = Column(String(100), nullable=True)

    donation_type = Column(String(20), nullable=False)  # garment, pantry

    garment_id = Column(Integer, ForeignKey('vistetec_garments.id'), nullable=True)

    pantry_item_id = Column(Integer, ForeignKey('vistetec_pantry_items.id'), nullable=True)
    quantity = Column(Integer, nullable=False, server_default=text("1"))
    campaign_id = Column(Integer, ForeignKey('vistetec_pantry_campaigns.id'), nullable=True)

    registered_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)
    notes = Column(Text)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    # Relaciones
    donor = relationship('User', foreign_keys=[donor_id], lazy='joined')
    garment = relationship('Garment', back_populates='donation', lazy='joined')
    pantry_item = relationship('PantryItem', back_populates='donations', lazy='joined')
    campaign = relationship('PantryCampaign', lazy='joined')
    registered_by = relationship('User', foreign_keys=[registered_by_id], lazy='joined')

    __table_args__ = (
        Index('ix_vistetec_donation_type', 'donation_type'),
        Index('ix_vistetec_donation_donor', 'donor_id'),
    )

    def __repr__(self):
        return f'<VTDonation {self.code} - {self.donation_type}>'

    def to_dict(self, include_relations=False):
        data = {
            'id': self.id,
            'code': self.code,
            'donor_id': self.donor_id,
            'donor_name': self.donor_name,
            'donation_type': self.donation_type,
            'garment_id': self.garment_id,
            'pantry_item_id': self.pantry_item_id,
            'quantity': self.quantity,
            'campaign_id': self.campaign_id,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_relations:
            data['donor'] = {
                'id': self.donor.id,
                'name': self.donor.full_name,
            } if self.donor else None
            data['garment'] = self.garment.to_dict() if self.garment else None
            data['pantry_item'] = self.pantry_item.to_dict() if self.pantry_item else None
            data['campaign'] = self.campaign.to_dict() if self.campaign else None
            data['registered_by'] = {
                'id': self.registered_by.id,
                'name': self.registered_by.full_name,
            } if self.registered_by else None
        return data
