from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base

appointment_status_pg_enum = ENUM(
    "SCHEDULED", "DONE", "NO_SHOW", "CANCELED",
    name="appointment_status_enum",
    create_type=False,
)


class Appointment(Base):
    __tablename__ = "agendatec_appointments"

    id = Column(BigInteger, primary_key=True)

    request_id = Column(
        BigInteger,
        ForeignKey("agendatec_requests.id", onupdate="CASCADE", ondelete="CASCADE"),
        unique=True,
    )
    student_id = Column(
        BigInteger,
        ForeignKey("core_users.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    coordinator_id = Column(
        Integer,
        ForeignKey("core_coordinators.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    program_id = Column(
        Integer,
        ForeignKey("core_programs.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    slot_id = Column(
        BigInteger,
        ForeignKey("agendatec_time_slots.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )

    status = Column(appointment_status_pg_enum, nullable=False, server_default="SCHEDULED")
    booked_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    # Relaciones
    request = relationship("Request", back_populates="appointment")
    student = relationship("User", back_populates="appointments")
    coordinator = relationship("Coordinator", back_populates="appointments")
    program = relationship("Program", back_populates="appointments")
    slot = relationship("TimeSlot", back_populates="appointments")

    def __repr__(self) -> str:
        return f"<Appointment {self.id} student={self.student_id} slot={self.slot_id} status={self.status}>"
