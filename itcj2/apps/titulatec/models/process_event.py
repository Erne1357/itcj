"""Auditoría / timeline de eventos de un proceso."""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class ProcessEvent(Base):
    __tablename__ = "titulatec_process_events"

    id = Column(Integer, primary_key=True)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"), nullable=False, index=True)
    actor_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    event_type = Column(String(40), nullable=False)                 # phase_approved|document_uploaded|synodal_voted|...
    phase_number = Column(Integer, nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"), index=True)

    process = relationship("TitulationProcess", back_populates="events")

    def __repr__(self) -> str:
        return f"<ProcessEvent p{self.process_id} {self.event_type}>"
