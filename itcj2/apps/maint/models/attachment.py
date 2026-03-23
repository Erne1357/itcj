from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class MaintAttachment(Base):
    """
    Archivos adjuntos de tickets de mantenimiento.

    attachment_type: 'ticket' | 'resolution' | 'comment'
    """
    __tablename__ = 'maint_attachments'

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey('maint_tickets.id'), nullable=False)
    uploaded_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)
    attachment_type = Column(String(30), nullable=False)
    comment_id = Column(Integer, ForeignKey('maint_comments.id'), nullable=True)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    filepath = Column(String(500), nullable=False)
    mime_type = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    auto_delete_at = Column(DateTime, nullable=True)  # 2 días tras resolución

    # Relaciones
    ticket = relationship('MaintTicket', back_populates='attachments',
                          foreign_keys=[ticket_id])
    uploaded_by = relationship('User', foreign_keys=[uploaded_by_id])
    comment = relationship('MaintComment', back_populates='attachments',
                           foreign_keys=[comment_id])

    __table_args__ = (
        Index('ix_maint_attachment_auto_delete', 'auto_delete_at'),
        Index('ix_maint_attachment_ticket_type', 'ticket_id', 'attachment_type'),
    )
