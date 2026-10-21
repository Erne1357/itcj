"""Asignación de sinodales a un proceso."""
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class SynodalAssignment(Base):
    __tablename__ = "titulatec_synodal_assignments"

    id = Column(Integer, primary_key=True)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False, index=True)  # sinodal
    role = Column(String(20), nullable=False)                       # president|secretary|vocal|alternate

    vote = Column(String(20), nullable=True)                        # approved|changes_requested|null
    vote_at = Column(DateTime, nullable=True)
    vote_note = Column(Text, nullable=True)

    assigned_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False)  # jefe vinculación
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    # Historial: una fila sustituida queda con is_active=False
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"), index=True)
    replaced_at = Column(DateTime, nullable=True)
    replaced_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    replacement_reason = Column(Text, nullable=True)

    process = relationship("TitulationProcess", back_populates="synodal_assignments")
    synodal = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("uq_titulatec_synodal_active_role", "process_id", "role",
              unique=True, postgresql_where=text("is_active")),
        Index("uq_titulatec_synodal_active_user", "process_id", "user_id",
              unique=True, postgresql_where=text("is_active")),
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
            "is_active": self.is_active,
        }
