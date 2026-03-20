from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, Time
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class VTTimeSlot(Base):
    """Slots de disponibilidad para atender citas (generales, no por voluntario)."""
    __tablename__ = 'vistetec_time_slots'

    id = Column(Integer, primary_key=True)
    created_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False, index=True)
    location_id = Column(Integer, ForeignKey('vistetec_locations.id'), nullable=True)

    date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)

    max_appointments = Column(Integer, nullable=False, server_default=text("1"))
    current_appointments = Column(Integer, nullable=False, server_default=text("0"))

    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"))

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    # Relaciones
    created_by = relationship('User', foreign_keys=[created_by_id], lazy='joined')
    location = relationship('VTLocation', back_populates='time_slots', lazy='joined')
    appointments = relationship('VTAppointment', back_populates='slot', lazy='dynamic')
    slot_volunteers = relationship('SlotVolunteer', back_populates='slot', lazy='dynamic')

    __table_args__ = (
        Index('ix_vistetec_slot_created_by_date', 'created_by_id', 'date'),
        Index('ix_vistetec_slot_date_active', 'date', 'is_active'),
    )

    def __repr__(self):
        return f'<VTTimeSlot {self.date} {self.start_time}-{self.end_time}>'

    @property
    def is_full(self):
        return self.current_appointments >= self.max_appointments

    @property
    def available_spots(self):
        return max(0, self.max_appointments - self.current_appointments)

    def to_dict(self, include_volunteers=False):
        data = {
            'id': self.id,
            'created_by_id': self.created_by_id,
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
        if include_volunteers:
            data['volunteers'] = [sv.to_dict() for sv in self.slot_volunteers.all()]
        if self.location:
            data['location'] = self.location.to_dict()
        return data
