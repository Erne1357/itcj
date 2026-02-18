from itcj.core.extensions import db


class SlotVolunteer(db.Model):
    """Relación N:N entre slots y voluntarios inscritos."""
    __tablename__ = 'vistetec_slot_volunteers'

    id = db.Column(db.Integer, primary_key=True)
    slot_id = db.Column(db.Integer, db.ForeignKey('vistetec_time_slots.id'), nullable=False, index=True)
    volunteer_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=False, index=True)

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))

    # Relaciones
    slot = db.relationship('itcj.apps.vistetec.models.time_slot.TimeSlot', back_populates='slot_volunteers')
    volunteer = db.relationship('User', foreign_keys=[volunteer_id], lazy='joined')

    __table_args__ = (
        db.UniqueConstraint('slot_id', 'volunteer_id', name='uq_slot_volunteer'),
    )

    def __repr__(self):
        return f'<SlotVolunteer slot={self.slot_id} volunteer={self.volunteer_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'slot_id': self.slot_id,
            'volunteer_id': self.volunteer_id,
            'volunteer_name': self.volunteer.full_name if self.volunteer else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
