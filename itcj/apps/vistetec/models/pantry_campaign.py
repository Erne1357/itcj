from itcj.core.extensions import db


class PantryCampaign(db.Model):
    """Campañas de recolección de despensa."""
    __tablename__ = 'vistetec_pantry_campaigns'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)

    requested_item_id = db.Column(db.Integer, db.ForeignKey('vistetec_pantry_items.id'), nullable=True)
    goal_quantity = db.Column(db.Integer, nullable=True)
    collected_quantity = db.Column(db.Integer, nullable=False, server_default=db.text("0"))

    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)

    is_active = db.Column(db.Boolean, nullable=False, server_default=db.text("TRUE"))

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    updated_at = db.Column(db.DateTime, server_default=db.text("NOW()"), onupdate=db.func.now())

    # Relaciones
    requested_item = db.relationship('PantryItem', back_populates='campaigns', lazy='joined')

    def __repr__(self):
        return f'<PantryCampaign {self.name}>'

    @property
    def progress_percentage(self):
        if not self.goal_quantity or self.goal_quantity == 0:
            return 0
        return min(100, round((self.collected_quantity / self.goal_quantity) * 100))

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'requested_item_id': self.requested_item_id,
            'requested_item': self.requested_item.to_dict() if self.requested_item else None,
            'goal_quantity': self.goal_quantity,
            'collected_quantity': self.collected_quantity,
            'progress_percentage': self.progress_percentage,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'is_active': self.is_active,
        }
