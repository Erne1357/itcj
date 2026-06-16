"""Acto protocolario (evento compartido) + M2M con procesos."""
from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class Ceremony(Base):
    """Evento de titulación que agrupa a varios alumnos."""
    __tablename__ = "titulatec_ceremonies"

    id = Column(Integer, primary_key=True)
    cohort_id = Column(Integer, ForeignKey("titulatec_cohorts.id"), nullable=True, index=True)
    scheduled_at = Column(DateTime, nullable=True)
    room = Column(String(60), nullable=True)
    whatsapp_group_url = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, server_default=text("'pending'"))  # pending|scheduled|done
    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    participants = relationship(
        "CeremonyProcess", back_populates="ceremony", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Ceremony {self.id} {self.status}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "cohort_id": self.cohort_id,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "room": self.room,
            "whatsapp_group_url": self.whatsapp_group_url,
            "status": self.status,
        }


class CeremonyProcess(Base):
    """Participación de un proceso en un acto. Cada alumno sube su trabajo y presentación."""
    __tablename__ = "titulatec_ceremony_processes"

    id = Column(Integer, primary_key=True)
    ceremony_id = Column(Integer, ForeignKey("titulatec_ceremonies.id"), nullable=False, index=True)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"), nullable=False, index=True)
    final_project_path = Column(String(255), nullable=True)         # final_project.pdf
    presentation_path = Column(String(255), nullable=True)          # presentation.pptx
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    ceremony = relationship("Ceremony", back_populates="participants")
    process = relationship("TitulationProcess")

    __table_args__ = (
        UniqueConstraint("ceremony_id", "process_id", name="uq_titulatec_ceremony_process"),
    )

    def __repr__(self) -> str:
        return f"<CeremonyProcess c{self.ceremony_id} p{self.process_id}>"
