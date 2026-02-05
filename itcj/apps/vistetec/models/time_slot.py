from itcj.core.extensions import db


class TimeSlot(db.Model):
    """Slots de disponibilidad de voluntarios para atender citas."""
    __tablename__ = 'vistetec_time_slots'

    id = db.Column(db.Integer, primary_key=True)
    volunteer_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=False, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey('vistetec_locations.id'), nullable=True)

    date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)

    max_appointments = db.Column(db.Integer, nullable=False, server_default=db.text("1"))
    current_appointments = db.Column(db.Integer, nullable=False, server_default=db.text("0"))

    is_active = db.Column(db.Boolean, nullable=False, server_default=db.text("TRUE"))

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))

    # Relaciones
    volunteer = db.relationship('User', foreign_keys=[volunteer_id], lazy='joined')
    location = db.relationship('Location', back_populates='time_slots', lazy='joined')
    appointments = db.relationship('itcj.apps.vistetec.models.appointment.Appointment', back_populates='slot', lazy='dynamic')

    __table_args__ = (
        db.Index('ix_vistetec_slot_volunteer_date', 'volunteer_id', 'date'),
        db.Index('ix_vistetec_slot_date_active', 'date', 'is_active'),
    )

    def __repr__(self):
        return f'<TimeSlot {self.date} {self.start_time}-{self.end_time}>'

    @property
    def is_full(self):
        return self.current_appointments >= self.max_appointments

    @property
    def available_spots(self):
        return max(0, self.max_appointments - self.current_appointments)

    def to_dict(self, include_volunteer=False):
        data = {
            'id': self.id,
            'volunteer_id': self.volunteer_id,
            'location_id': self.location_id,
            'date': self.date.isoformat() if self.date else None,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'max_appointments': self.max_appointments,
            'current_appointments': self.current_appointments,
            'available_spots': self.available_spots,
            'is_full': self.is_full,
            'is_active': self.is_active,
        }
        if include_volunteer and self.volunteer:
            data['volunteer'] = {
                'id': self.volunteer.id,
                'name': self.volunteer.full_name,
            }
        if self.location:
            data['location'] = self.location.to_dict()
        return data
