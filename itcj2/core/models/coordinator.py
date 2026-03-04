from sqlalchemy import Column, Integer, BigInteger, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class Coordinator(Base):
    __tablename__ = "core_coordinators"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        BigInteger,
        ForeignKey("core_users.id", onupdate="CASCADE", ondelete="CASCADE"),
        unique=True, nullable=False,
    )
    contact_email = Column(Text)
    office_hours = Column(Text)
    must_change_pw = Column(Boolean, nullable=False, server_default=text("TRUE"))

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    user = relationship("User", back_populates="coordinator")
    program_coordinators = relationship(
        "ProgramCoordinator", back_populates="coordinator",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    programs = relationship(
        "Program",
        secondary="core_program_coordinator",
        back_populates="coordinators",
        viewonly=True,
    )
    availability_windows = relationship(
        "AvailabilityWindow", back_populates="coordinator",
        cascade="all, delete", passive_deletes=True,
    )
    time_slots = relationship(
        "itcj2.apps.agendatec.models.time_slot.TimeSlot",
        back_populates="coordinator",
        cascade="all, delete", passive_deletes=True,
    )
    appointments = relationship(
        "itcj2.apps.agendatec.models.appointment.Appointment",
        back_populates="coordinator",
        cascade="all, delete", passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Coordinator {self.id} user={self.user_id}>"
