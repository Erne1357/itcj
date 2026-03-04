from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import relationship

from itcj2.models.base import Base


class ProgramCoordinator(Base):
    __tablename__ = "core_program_coordinator"

    program_id = Column(Integer, ForeignKey("core_programs.id", onupdate="CASCADE", ondelete="CASCADE"), primary_key=True)
    coordinator_id = Column(Integer, ForeignKey("core_coordinators.id", onupdate="CASCADE", ondelete="CASCADE"), primary_key=True)

    program = relationship("Program", back_populates="program_coordinators")
    coordinator = relationship("Coordinator", back_populates="program_coordinators")

    def __repr__(self) -> str:
        return f"<ProgramCoordinator program={self.program_id} coord={self.coordinator_id}>"
