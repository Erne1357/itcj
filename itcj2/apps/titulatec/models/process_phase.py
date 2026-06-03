"""Instancia de una fase para un proceso de titulación."""
from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class ProcessPhase(Base):
    __tablename__ = "titulatec_process_phases"

    id = Column(Integer, primary_key=True)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"), nullable=False, index=True)
    phase_number = Column(Integer, nullable=False)                   # 0..8
    status = Column(String(20), nullable=False, server_default=text("'pending'"))  # pending|in_progress|in_review|approved|rejected|skipped

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    reviewed_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    rejection_reason = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    process = relationship("TitulationProcess", back_populates="phases")

    __table_args__ = (
        UniqueConstraint("process_id", "phase_number", name="uq_titulatec_phase_process_number"),
    )

    def __repr__(self) -> str:
        return f"<ProcessPhase p{self.process_id}#{self.phase_number}:{self.status}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "process_id": self.process_id,
            "phase_number": self.phase_number,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "rejection_reason": self.rejection_reason,
        }
