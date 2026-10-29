from sqlalchemy import (
    JSON, BigInteger, Column, DateTime, ForeignKey, SmallInteger, String, Text, UniqueConstraint,
)
from sqlalchemy.sql import text

from itcj2.models.base import Base


class ProrrogaDocument(Base):
    """Documento generado (formato, carta) de una solicitud; versionado."""
    __tablename__ = "prorrogas_documents"

    id = Column(BigInteger, primary_key=True)
    request_id = Column(BigInteger, ForeignKey("prorrogas_requests.id", ondelete="CASCADE"), nullable=False)
    doc_type = Column(String(40))
    version = Column(SmallInteger)
    template_id = Column(ForeignKey("prorrogas_templates.id", ondelete="SET NULL"))
    context = Column(JSON, nullable=False)
    file_path = Column(Text)
    sha256 = Column(String(64))
    generated_by_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="SET NULL"))
    generated_at = Column(DateTime, server_default=text("NOW()"))
    signed_at = Column(DateTime)
    superseded_at = Column(DateTime)

    __table_args__ = (UniqueConstraint("request_id", "doc_type", "version", name="uq_prorrogas_documents_version"),)
