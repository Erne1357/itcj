"""Revisión de sinodales (fase 5): versiones del proyecto, votos y recordatorios.

Spec 2026-10-22-titulatec-fase5-revision-sinodales §5. Las versiones y los votos
cuelgan del PROCESO (no del chat): el chat solo los muestra como mensajes de
sistema (`ChatMessage.kind` = ``version`` | ``vote``).
"""
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base

# Veredictos de un voto. El sentido de «cuántos votos cuentan» NO vive aquí: lo
# decide `ReviewService.counting_roles(signature_rule)` (nunca la modalidad).
VOTE_VERDICTS = ("approved", "changes_requested")

# Recordatorios por vencer enviados a un sinodal por versión (idempotencia).
REMINDER_KINDS = ("due_soon", "due_today")


class ReviewVersion(Base):
    """Una versión del proyecto subida por el alumno para revisión de sinodales."""
    __tablename__ = "titulatec_review_versions"

    id = Column(Integer, primary_key=True)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"), nullable=False, index=True)
    number = Column(Integer, nullable=False)                      # 1, 2, 3... por proceso

    file_path = Column(String(255), nullable=True)
    original_name = Column(String(255), nullable=True)
    mime_type = Column(String(100), nullable=True)
    size_bytes = Column(Integer, nullable=True)

    uploaded_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False)
    uploaded_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    process = relationship("TitulationProcess")
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_id])
    votes = relationship("ReviewVote", back_populates="version",
                         cascade="all, delete-orphan", order_by="ReviewVote.id")

    __table_args__ = (
        UniqueConstraint("process_id", "number",
                         name="uq_titulatec_review_versions_process_number"),
    )

    def __repr__(self) -> str:
        return f"<ReviewVersion p{self.process_id} v{self.number}>"


class ReviewVote(Base):
    """Voto de UNA asignación vigente sobre UNA versión (se puede cambiar mientras
    la versión está abierta: `updated_at`)."""
    __tablename__ = "titulatec_review_votes"

    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey("titulatec_review_versions.id"),
                        nullable=False, index=True)
    assignment_id = Column(Integer, ForeignKey("titulatec_synodal_assignments.id"),
                           nullable=False)
    user_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False)

    verdict = Column(String(20), nullable=False)                  # approved | changes_requested
    comment = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=True, onupdate=func.now())

    version = relationship("ReviewVersion", back_populates="votes")
    assignment = relationship("SynodalAssignment")
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("version_id", "assignment_id",
                         name="uq_titulatec_review_votes_version_assignment"),
        CheckConstraint("verdict IN ('approved', 'changes_requested')",
                        name="ck_titulatec_review_votes_verdict"),
    )

    def __repr__(self) -> str:
        return f"<ReviewVote v{self.version_id} a{self.assignment_id} {self.verdict}>"


class ReviewReminder(Base):
    """Recordatorio ya enviado (PK compuesta: una vez por versión, sinodal y tipo)."""
    __tablename__ = "titulatec_review_reminders"

    version_id = Column(Integer, ForeignKey("titulatec_review_versions.id"), primary_key=True)
    assignment_id = Column(Integer, ForeignKey("titulatec_synodal_assignments.id"),
                           primary_key=True)
    kind = Column(String(20), primary_key=True)                   # due_soon | due_today
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    def __repr__(self) -> str:
        return f"<ReviewReminder v{self.version_id} a{self.assignment_id} {self.kind}>"
