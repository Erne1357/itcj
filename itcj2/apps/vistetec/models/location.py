from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class VTLocation(Base):
    """Ubicaciones donde se atienden citas de VisteTec."""
    __tablename__ = 'vistetec_locations'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"))

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    # Relaciones
    time_slots = relationship('VTTimeSlot', back_populates='location', lazy='dynamic')
    appointments = relationship('VTAppointment', back_populates='location', lazy='dynamic')

    def __repr__(self):
        return f'<VTLocation {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'is_active': self.is_active,
        }
