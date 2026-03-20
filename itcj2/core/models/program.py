from sqlalchemy import Column, Integer, Text, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class Program(Base):
    __tablename__ = "core_programs"

    id = Column(Integer, primary_key=True)
    name = Column(Text, unique=True, nullable=False)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    program_coordinators = relationship(
        "ProgramCoordinator", back_populates="program",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    coordinators = relationship(
        "Coordinator",
        secondary="core_program_coordinator",
        back_populates="programs",
        viewonly=True,
    )
    requests = relationship(
        "Request", back_populates="program",
        cascade="all, delete", passive_deletes=True,
    )
    appointments = relationship(
        "itcj2.apps.agendatec.models.appointment.Appointment",
        back_populates="program",
        cascade="all, delete", passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Program {self.name}>"
