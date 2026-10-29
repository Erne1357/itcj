from sqlalchemy import JSON, BigInteger, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.sql import text

from itcj2.models.base import Base


class ProrrogaEvent(Base):
    """Bitácora de lo que pasa con una solicitud."""
    __tablename__ = "prorrogas_events"

    id = Column(BigInteger, primary_key=True)
    request_id = Column(BigInteger, ForeignKey("prorrogas_requests.id", ondelete="CASCADE"))
    actor_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="SET NULL"))
    event_type = Column(String(40))
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    __table_args__ = (Index("ix_prorrogas_events_solicitud", "request_id", "created_at"),)
