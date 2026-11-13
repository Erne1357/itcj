from sqlalchemy import (
    JSON, BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text,
)
from sqlalchemy.sql import text

from itcj2.models.base import Base


class ProrrogaTemplate(Base):
    """Plantilla ``.docx`` que subió la secretaria para un formato y un año.

    No se borra ni se edita: la más reciente de su (formato, año) es la que se
    usa. Ver ``services/template_service.py`` y spec §6.3.
    """
    __tablename__ = "prorrogas_templates"

    id = Column(Integer, primary_key=True)
    doc_type = Column(String(40), nullable=False)
    year = Column(SmallInteger, nullable=False)
    original_name = Column(Text, nullable=False)
    # Relativa a PRORROGAS_UPLOAD_PATH: templates/{año}/{tipo}-{sha12}.docx
    file_path = Column(Text, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    placeholders = Column(JSON, nullable=False)
    uploaded_by_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="SET NULL"), nullable=True)
    uploaded_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        CheckConstraint("year BETWEEN 2020 AND 2100", name="ck_prorrogas_templates_year"),
        Index("ix_prorrogas_templates_tipo_anio", "doc_type", "year", "uploaded_at"),
    )

    def __repr__(self) -> str:
        return f"<ProrrogaTemplate {self.doc_type} {self.year} id={self.id}>"
