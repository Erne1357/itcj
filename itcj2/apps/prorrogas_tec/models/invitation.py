from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.sql import text

from itcj2.models.base import Base


class ProrrogaInvitation(Base):
    """Invitación manual (enlace de un solo uso, 48 h); solo se guarda el sha256 del token."""
    __tablename__ = "prorrogas_invitations"

    id = Column(BigInteger, primary_key=True)
    control_number = Column(Text)
    email = Column(Text)
    user_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="CASCADE"), nullable=False)
    token_sha256 = Column(String(64), unique=True)
    expires_at = Column(DateTime)
    created_by_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="SET NULL"))
    user_created = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    used_at = Column(DateTime)


class ProrrogaJoin(Base):
    """Unión de un alumno a la app (por QR o invitación): la puerta para pedir prórroga."""
    __tablename__ = "prorrogas_joins"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="CASCADE"))
    via = Column(String(12))
    invitation_id = Column(BigInteger, ForeignKey("prorrogas_invitations.id", ondelete="SET NULL"))
    issued_by_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="SET NULL"))
    joined_at = Column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint("via IN ('qr','invitacion')", name="ck_prorrogas_joins_via"),
        Index("ix_prorrogas_joins_usuario", "user_id", "joined_at"),
    )
