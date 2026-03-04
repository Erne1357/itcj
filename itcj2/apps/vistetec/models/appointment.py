from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class VTAppointment(Base):
    """Cita de un estudiante para probarse una prenda."""
    __tablename__ = 'vistetec_appointments'

    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False, index=True)

    student_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False, index=True)
    garment_id = Column(Integer, ForeignKey('vistetec_garments.id'), nullable=False, index=True)
    slot_id = Column(Integer, ForeignKey('vistetec_time_slots.id'), nullable=False)
    location_id = Column(Integer, ForeignKey('vistetec_locations.id'), nullable=True)

    status = Column(String(20), nullable=False, server_default=text("'scheduled'"), index=True)
    # scheduled, attended, no_show, cancelled, completed

    outcome = Column(String(20), nullable=True)  # taken, not_fit, declined
    notes = Column(Text)

    will_bring_donation = Column(Boolean, nullable=True, server_default=text("FALSE"))

    attended_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)
    attended_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, server_default=text("NOW()"), onupdate=func.now())

    # Relaciones
    student = relationship('User', foreign_keys=[student_id], lazy='joined')
    garment = relationship('Garment', back_populates='appointments', lazy='joined')
    slot = relationship('VTTimeSlot', back_populates='appointments', lazy='joined')
    location = relationship('VTLocation', back_populates='appointments', lazy='joined')
    attended_by = relationship('User', foreign_keys=[attended_by_id], lazy='joined')

    __table_args__ = (
        Index('ix_vistetec_appt_student_status', 'student_id', 'status'),
        Index('ix_vistetec_appt_garment_status', 'garment_id', 'status'),
    )

    def __repr__(self):
        return f'<VTAppointment {self.code} - {self.status}>'

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
            'will_bring_donation': self.will_bring_donation,
            'attended_at': self.attended_at.isoformat() if self.attended_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_relations:
            data['student'] = {
                'id': self.student.id,
                'name': self.student.full_name,
                'control_number': self.student.control_number,
            } if self.student else None
            data['garment'] = self.garment.to_dict() if self.garment else None
            data['slot'] = self.slot.to_dict() if self.slot else None
            data['location'] = self.location.to_dict() if self.location else None
            data['attended_by'] = {
                'id': self.attended_by.id,
                'name': self.attended_by.full_name,
            } if self.attended_by else None
        return data
