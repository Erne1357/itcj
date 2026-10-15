"""Documento del proceso. Solo se conserva la última versión (uq process+type)."""
from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class Document(Base):
    __tablename__ = "titulatec_documents"

    id = Column(Integer, primary_key=True)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"), nullable=False, index=True)
    phase_number = Column(Integer, nullable=False, index=True)
    type_code = Column(String(40), nullable=False)                  # FK lógico a titulatec_document_types.code

    file_path = Column(String(255), nullable=False)                 # relativa a TITULATEC_UPLOAD_PATH
    original_name = Column(String(255), nullable=True)
    mime_type = Column(String(100), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    # Contador informativo de subidas de ese (proceso, tipo). Continúa tras borrar
    # y volver a subir (`DocumentService._next_version`, 2026-10-15): una fila
    # nueva no arranca en 1 si la bitácora ya tiene subidas de ese tipo.
    version = Column(Integer, nullable=False, server_default=text("1"))

    review_status = Column(String(20), nullable=False, server_default=text("'pending'"))  # pending|approved|rejected
    reviewed_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    review_note = Column(Text, nullable=True)
    uploaded_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False)

    # REEMPLAZO ABIERTO en la cita de cotejo (spec 2026-10-15-titulatec-
    # reemplazo-cotejo-design.md §3): no NULL = la jefatura de Servicios
    # Escolares pidió que el egresado vuelva a subir este documento de la fase 1
    # estando ya en la fase 2. La escribe SOLO `DocumentService.
    # request_replacement` (la primera vez; pedirlo otra vez conserva la fecha)
    # y la limpia SOLO `DocumentService.review(status="approved")`; `save()` no
    # la toca. Sin «quién»: lo guardan el `ProcessEvent` y la bitácora.
    # Migración `tt20261015a`.
    replacement_requested_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    process = relationship("TitulationProcess", back_populates="documents")

    __table_args__ = (
        UniqueConstraint("process_id", "type_code", name="uq_titulatec_document_process_type"),
    )

    def __repr__(self) -> str:
        return f"<Document p{self.process_id}:{self.type_code}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "process_id": self.process_id,
            "phase_number": self.phase_number,
            "type_code": self.type_code,
            "original_name": self.original_name,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "version": self.version,
            "review_status": self.review_status,
            "review_note": self.review_note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
