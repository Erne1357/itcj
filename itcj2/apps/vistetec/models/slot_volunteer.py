from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class SlotVolunteer(Base):
    """Relación N:N entre slots y voluntarios inscritos."""
    __tablename__ = 'vistetec_slot_volunteers'

    id = Column(Integer, primary_key=True)
    slot_id = Column(Integer, ForeignKey('vistetec_time_slots.id'), nullable=False, index=True)
    volunteer_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False, index=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    # Relaciones
    slot = relationship('VTTimeSlot', back_populates='slot_volunteers')
    volunteer = relationship('User', foreign_keys=[volunteer_id], lazy='joined')

    __table_args__ = (
        UniqueConstraint('slot_id', 'volunteer_id', name='uq_slot_volunteer'),
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
