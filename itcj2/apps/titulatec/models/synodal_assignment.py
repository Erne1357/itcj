"""Asignación de sinodales a un proceso."""
from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class SynodalAssignment(Base):
    __tablename__ = "titulatec_synodal_assignments"

    id = Column(Integer, primary_key=True)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False, index=True)  # sinodal
    role = Column(String(20), nullable=False)                       # president|secretary|vocal

    vote = Column(String(20), nullable=True)                        # approved|changes_requested|null
    vote_at = Column(DateTime, nullable=True)
    vote_note = Column(Text, nullable=True)

    assigned_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False)  # jefe vinculación
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    process = relationship("TitulationProcess", back_populates="synodal_assignments")
    synodal = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("process_id", "user_id", name="uq_titulatec_synodal_process_user"),
    )

    def __repr__(self) -> str:
        return f"<SynodalAssignment p{self.process_id} u{self.user_id} {self.role}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "process_id": self.process_id,
            "user_id": self.user_id,
            "role": self.role,
            "vote": self.vote,
            "vote_at": self.vote_at.isoformat() if self.vote_at else None,
            "vote_note": self.vote_note,
        }
