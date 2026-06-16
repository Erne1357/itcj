"""Proceso de titulación — entidad raíz (1 por alumno × convocatoria)."""
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class TitulationProcess(Base):
    __tablename__ = "titulatec_processes"

    id = Column(Integer, primary_key=True)
    folio = Column(String(20), unique=True, nullable=False, index=True)  # 'TT-2026A-0094'

    student_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False, index=True)
    cohort_id = Column(Integer, ForeignKey("titulatec_cohorts.id"), nullable=False, index=True)
    program_id = Column(Integer, ForeignKey("core_programs.id"), nullable=True)   # carrera (reusa core_programs)
    modality_id = Column(Integer, ForeignKey("titulatec_modalities.id"), nullable=True)

    current_phase = Column(Integer, nullable=False, server_default=text("0"))     # 0..8
    status = Column(String(20), nullable=False, server_default=text("'active'"), index=True)  # active|completed|cancelled|on_hold
    is_app_active = Column(Boolean, nullable=False, server_default=text("TRUE"), index=True)   # bloqueo login app-level (≠ SII)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    # Relaciones
    student = relationship("User", foreign_keys=[student_id])
    cohort = relationship("Cohort", back_populates="processes")
    modality = relationship("Modality")
    phases = relationship("ProcessPhase", back_populates="process", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="process", cascade="all, delete-orphan")
    format_b = relationship("FormatB", back_populates="process", uselist=False, cascade="all, delete-orphan")
    synodal_assignments = relationship("SynodalAssignment", back_populates="process", cascade="all, delete-orphan")
    chat = relationship("ProcessChat", back_populates="process", uselist=False, cascade="all, delete-orphan")
    review_appointments = relationship("ReviewAppointment", back_populates="process", cascade="all, delete-orphan")
    events = relationship("ProcessEvent", back_populates="process", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("student_id", "cohort_id", name="uq_titulatec_process_student_cohort"),
    )

    def __repr__(self) -> str:
        return f"<TitulationProcess {self.folio}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "folio": self.folio,
            "student_id": self.student_id,
            "cohort_id": self.cohort_id,
            "program_id": self.program_id,
            "modality_id": self.modality_id,
            "current_phase": self.current_phase,
            "status": self.status,
            "is_app_active": self.is_app_active,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
