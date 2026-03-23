from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class MaintStatusLog(Base):
    """Auditoría de cambios de estado del ticket."""
    __tablename__ = 'maint_status_logs'

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey('maint_tickets.id'), nullable=False)
    from_status = Column(String(30), nullable=True)   # NULL en el primer registro
    to_status = Column(String(30), nullable=False)
    changed_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    # Relaciones
    ticket = relationship('MaintTicket', back_populates='status_logs')
    changed_by = relationship('User', foreign_keys=[changed_by_id])

    __table_args__ = (
        Index('ix_maint_status_log_ticket_date', 'ticket_id', 'created_at'),
        Index('ix_maint_status_log_user_date', 'changed_by_id', 'created_at'),
    )
