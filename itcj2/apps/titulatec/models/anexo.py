"""Anexo III (fase 6): folio del documento y su contador por semestre.

Spec 2026-10-22-titulatec-fase6-anexo-iii §4-§5. Un proceso tiene a lo mas UN
anexo; su folio (`AIII-2026B-0001`) se consume una sola vez y no se reutiliza.
"""
from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint,
)
from sqlalchemy.sql import text

from itcj2.models.base import Base


class Anexo(Base):
    """Anexo III emitido. `released_at` congela la fecha de liberacion de la
    revision de sinodales (fase 5)."""
    __tablename__ = "titulatec_anexos"

    id = Column(Integer, primary_key=True)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"), nullable=False)
    folio = Column(String(20), nullable=False)
    semester = Column(String(5), nullable=False)           # '2026A' / '2026B'
    released_at = Column(DateTime, nullable=False)
    issued_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    issued_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    # Entrega (spec 2026-10-29 fase 6 v2 §5): vinculacion lo marca «Listo para
    # recoger». La etapa la lee SOLO `AnexoService.stage`/`stage_map`.
    ready_at = Column(DateTime, nullable=True)
    ready_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    pickup_note = Column(String(300), nullable=True)       # se conserva al pedir reimpresion
    reprint_reason = Column(String(500), nullable=True)
    reprint_requested_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("process_id", name="uq_titulatec_anexos_process"),
        UniqueConstraint("folio", name="uq_titulatec_anexos_folio"),
    )

    def __repr__(self) -> str:
        return f"<Anexo {self.folio}>"


class AnexoCounter(Base):
    """Contador atomico de folios de Anexo III por semestre."""
    __tablename__ = "titulatec_anexo_counters"

    semester = Column(String(5), primary_key=True)
    last_value = Column(Integer, nullable=False, server_default=text("0"))
