from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class AuditLog(Base):
    __tablename__ = "agendatec_audit_logs"

    id = Column(BigInteger, primary_key=True)

    actor_id = Column(BigInteger, ForeignKey("core_users.id", onupdate="CASCADE", ondelete="SET NULL"))
    action = Column(Text, nullable=False)    # e.g. 'REQUEST_STATUS_CHANGED'
    entity = Column(Text, nullable=False)    # e.g. 'requests', 'appointments'
    entity_id = Column(BigInteger)           # affected row id
    payload_json = Column(JSON)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    actor = relationship("User", back_populates="audit_logs")

    def __repr__(self) -> str:
        return f"<AuditLog {self.id} actor={self.actor_id} action={self.action} entity={self.entity}:{self.entity_id}>"
