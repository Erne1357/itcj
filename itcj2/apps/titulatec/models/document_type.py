"""Catálogo de tipos de documento del proceso de titulación."""
from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.sql import text

from itcj2.models.base import Base


class DocumentType(Base):
    """Tipo de documento (acta, curp, anexo_iii, ...) con sus reglas."""
    __tablename__ = "titulatec_document_types"

    id = Column(Integer, primary_key=True)
    code = Column(String(40), unique=True, nullable=False)           # 'birth_certificate','curp','anexo_iii',...
    name = Column(String(120), nullable=False)
    phase_number = Column(Integer, nullable=True)                    # fase a la que pertenece por defecto
    file_kind = Column(String(10), nullable=False, server_default=text("'pdf'"))  # 'pdf' | 'image'
    max_size = Column(Integer, nullable=True)                        # override de config (bytes)
    is_versionable = Column(Boolean, nullable=False, server_default=text("TRUE"))
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"), index=True)

    def __repr__(self) -> str:
        return f"<DocumentType {self.code}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "phase_number": self.phase_number,
            "file_kind": self.file_kind,
            "max_size": self.max_size,
            "is_versionable": self.is_versionable,
            "is_active": self.is_active,
        }
