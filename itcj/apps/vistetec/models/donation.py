from itcj.core.extensions import db


class Donation(db.Model):
    """Registro de donaciones de ropa o despensa."""
    __tablename__ = 'vistetec_donations'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)  # DON-2025-0001

    donor_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=True)
    donor_name = db.Column(db.String(100), nullable=True)  # Si es anónimo o externo

    donation_type = db.Column(db.String(20), nullable=False)  # garment, pantry

    # Si es prenda
    garment_id = db.Column(db.Integer, db.ForeignKey('vistetec_garments.id'), nullable=True)

    # Si es despensa
    pantry_item_id = db.Column(db.Integer, db.ForeignKey('vistetec_pantry_items.id'), nullable=True)
    quantity = db.Column(db.Integer, nullable=False, server_default=db.text("1"))

    registered_by_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=True)
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))

    # Relaciones
    donor = db.relationship('User', foreign_keys=[donor_id], lazy='joined')
    garment = db.relationship('Garment', back_populates='donation', lazy='joined')
    pantry_item = db.relationship('PantryItem', back_populates='donations', lazy='joined')
    registered_by = db.relationship('User', foreign_keys=[registered_by_id], lazy='joined')

    __table_args__ = (
        db.Index('ix_vistetec_donation_type', 'donation_type'),
        db.Index('ix_vistetec_donation_donor', 'donor_id'),
    )

    def __repr__(self):
        return f'<Donation {self.code} - {self.donation_type}>'

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
            data['registered_by'] = {
                'id': self.registered_by.id,
                'name': self.registered_by.full_name,
            } if self.registered_by else None
        return data
