from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, Text

from itcj2.models.base import Base


class ProrrogaSignature(Base):
    __tablename__ = "prorrogas_signatures"

    id = Column(BigInteger, primary_key=True)
    document_id = Column(BigInteger, ForeignKey("prorrogas_documents.id", ondelete="CASCADE"), nullable=False)
    signer_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="RESTRICT"), nullable=False)
    image_path = Column(Text)
    signed_at = Column(DateTime, nullable=False)
    ip = Column(String(64))
    user_agent = Column(Text)
    pdf_sha256 = Column(String(64))
