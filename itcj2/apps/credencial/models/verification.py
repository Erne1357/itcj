"""Bitacora de verificaciones del QR de la credencial."""
from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from itcj2.models.base import Base


class CredentialVerification(Base):
    __tablename__ = "credencial_verifications"

    id = Column(Integer, primary_key=True)
    student_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="CASCADE"), nullable=False, index=True)
    verifier_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="SET NULL"), nullable=True, index=True)
    result = Column(String(20), nullable=False)
    token_issued_at = Column(DateTime, nullable=False)
    verified_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        CheckConstraint("result IN ('valid','inactive')", name="ck_credencial_verifications_result"),
    )

    def __repr__(self):
        return f"<CredentialVerification student={self.student_id} result={self.result}>"
