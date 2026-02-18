from itcj.core.extensions import db


class PantryItem(db.Model):
    """Tipos de artículos de despensa que se reciben."""
    __tablename__ = 'vistetec_pantry_items'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=True)  # enlatados, granos, higiene, mascotas
    unit = db.Column(db.String(20), nullable=True)       # pieza, kg, litro

    current_stock = db.Column(db.Integer, nullable=False, server_default=db.text("0"))

    is_active = db.Column(db.Boolean, nullable=False, server_default=db.text("TRUE"))

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))

    # Relaciones
    donations = db.relationship('Donation', back_populates='pantry_item', lazy='dynamic')
    campaigns = db.relationship('PantryCampaign', back_populates='requested_item', lazy='dynamic')

    def __repr__(self):
        return f'<PantryItem {self.name} ({self.current_stock} {self.unit or "pzas"})>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'unit': self.unit,
            'current_stock': self.current_stock,
            'is_active': self.is_active,
        }
