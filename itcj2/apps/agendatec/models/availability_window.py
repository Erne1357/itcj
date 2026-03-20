from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Time
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class AvailabilityWindow(Base):
    __tablename__ = "agendatec_availability_windows"

    id = Column(Integer, primary_key=True)
    coordinator_id = Column(
        Integer,
        ForeignKey("core_coordinators.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )

    day = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    slot_minutes = Column(Integer, nullable=False, server_default=text("10"))

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    coordinator = relationship("Coordinator", back_populates="availability_windows")

    def __repr__(self) -> str:
        return f"<AvailabilityWindow coord={self.coordinator_id} {self.day} {self.start_time}-{self.end_time}>"
