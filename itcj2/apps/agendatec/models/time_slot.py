from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Integer, Time
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class TimeSlot(Base):
    __tablename__ = "agendatec_time_slots"

    id = Column(BigInteger, primary_key=True)
    coordinator_id = Column(
        Integer,
        ForeignKey("core_coordinators.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )

    day = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    is_booked = Column(Boolean, nullable=False, server_default=text("FALSE"))

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    coordinator = relationship("Coordinator", back_populates="time_slots")
    appointments = relationship(
        "Appointment",
        back_populates="slot",
        cascade="all, delete",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<TimeSlot {self.id} coord={self.coordinator_id} {self.start_time}-{self.end_time} booked={self.is_booked}>"
