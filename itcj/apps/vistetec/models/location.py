from itcj.core.extensions import db


class Location(db.Model):
    """Ubicaciones donde se atienden citas de VisteTec."""
    __tablename__ = 'vistetec_locations'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, server_default=db.text("TRUE"))

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))

    # Relaciones
    time_slots = db.relationship('itcj.apps.vistetec.models.time_slot.TimeSlot', back_populates='location', lazy='dynamic')
    appointments = db.relationship('itcj.apps.vistetec.models.appointment.Appointment', back_populates='location', lazy='dynamic')

    def __repr__(self):
        return f'<Location {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'is_active': self.is_active,
        }
