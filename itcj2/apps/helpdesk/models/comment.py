from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class Comment(Base):
    """
    Comentarios en tickets.
    Pueden ser públicos (visibles para el usuario) o internos (solo staff).
    """
    __tablename__ = 'helpdesk_comment'

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey('helpdesk_ticket.id'), nullable=False, index=True)
    author_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)

    # Contenido
    content = Column(Text, nullable=False)

    # Visibilidad
    is_internal = Column(Boolean, default=False, nullable=False)
    # True = Solo visible para staff; False = Visible para todos

    # Timestamps
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, server_default=text("NOW()"))

    # Relaciones
    ticket = relationship('Ticket', back_populates='comments')
    author = relationship('User', foreign_keys=[author_id])
    attachments = relationship('Attachment', back_populates='comment', lazy='select')

    # Índice
    __table_args__ = (
        Index('ix_helpdesk_comment_ticket_created', 'ticket_id', 'created_at'),
    )

    def __repr__(self):
        return f'<Comment on Ticket#{self.ticket_id} by {self.author_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'ticket_id': self.ticket_id,
            'content': self.content,
            'is_internal': self.is_internal,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'author': {
                'id': self.author.id,
                'name': self.author.full_name,
                'username': self.author.username,
            } if self.author else None,
            'attachments': [att.to_dict() for att in self.attachments] if self.attachments else [],
        }
