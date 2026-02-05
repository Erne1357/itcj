from itcj.core.extensions import db


class Appointment(db.Model):
    """Cita de un estudiante para probarse una prenda."""
    __tablename__ = 'vistetec_appointments'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)  # CIT-2025-0001

    student_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=False, index=True)
    garment_id = db.Column(db.Integer, db.ForeignKey('vistetec_garments.id'), nullable=False, index=True)
    slot_id = db.Column(db.Integer, db.ForeignKey('vistetec_time_slots.id'), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('vistetec_locations.id'), nullable=True)

    status = db.Column(db.String(20), nullable=False, server_default=db.text("'scheduled'"), index=True)
    # scheduled, attended, no_show, cancelled, completed

    # Resultado de la cita
    outcome = db.Column(db.String(20), nullable=True)  # taken, not_fit, declined
    notes = db.Column(db.Text)

    attended_by_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=True)
    attended_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    updated_at = db.Column(db.DateTime, server_default=db.text("NOW()"), onupdate=db.func.now())

    # Relaciones
    student = db.relationship('User', foreign_keys=[student_id], lazy='joined')
    garment = db.relationship('Garment', back_populates='appointments', lazy='joined')
    slot = db.relationship('itcj.apps.vistetec.models.time_slot.TimeSlot', back_populates='appointments', lazy='joined')
    location = db.relationship('Location', back_populates='appointments', lazy='joined')
    attended_by = db.relationship('User', foreign_keys=[attended_by_id], lazy='joined')

    __table_args__ = (
        db.Index('ix_vistetec_appt_student_status', 'student_id', 'status'),
        db.Index('ix_vistetec_appt_garment_status', 'garment_id', 'status'),
    )

    def __repr__(self):
        return f'<Appointment {self.code} - {self.status}>'

    def to_dict(self, include_relations=False):
        data = {
            'id': self.id,
            'code': self.code,
            'student_id': self.student_id,
            'garment_id': self.garment_id,
            'slot_id': self.slot_id,
            'location_id': self.location_id,
            'status': self.status,
            'outcome': self.outcome,
            'notes': self.notes,
            'attended_at': self.attended_at.isoformat() if self.attended_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_relations:
            data['student'] = {
                'id': self.student.id,
                'name': self.student.full_name,
            } if self.student else None
            data['garment'] = self.garment.to_dict() if self.garment else None
            data['slot'] = self.slot.to_dict() if self.slot else None
            data['location'] = self.location.to_dict() if self.location else None
            data['attended_by'] = {
                'id': self.attended_by.id,
                'name': self.attended_by.full_name,
            } if self.attended_by else None
        return data
