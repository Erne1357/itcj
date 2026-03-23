from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class MaintComment(Base):
    """Comentarios en tickets de mantenimiento."""
    __tablename__ = 'maint_comments'

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey('maint_tickets.id'), nullable=False)
    author_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)
    content = Column(Text, nullable=False)
    is_internal = Column(Boolean, nullable=False, server_default=text("FALSE"))
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=True)

    # Relaciones
    ticket = relationship('MaintTicket', back_populates='comments')
    author = relationship('User', foreign_keys=[author_id])
    attachments = relationship('MaintAttachment', back_populates='comment',
                               foreign_keys='MaintAttachment.comment_id')

    __table_args__ = (
        Index('ix_maint_comment_ticket_date', 'ticket_id', 'created_at'),
    )
