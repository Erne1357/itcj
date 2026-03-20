import os
from datetime import datetime, timedelta

from sqlalchemy import Column, BigInteger, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class Attachment(Base):
    """
    Archivos adjuntos a tickets (solo imágenes).
    Se auto-eliminan X días después de que el ticket se resuelve.
    """
    __tablename__ = 'helpdesk_attachment'

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey('helpdesk_ticket.id'), nullable=False, index=True)
    uploaded_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)

    # Tipo: 'ticket' (foto inicial), 'resolution', 'comment'
    attachment_type = Column(String(20), nullable=False, default='ticket', server_default='ticket')
    comment_id = Column(Integer, ForeignKey('helpdesk_comment.id'), nullable=True, index=True)

    # Información del archivo
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    filepath = Column(String(500), nullable=False)
    mime_type = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=True)

    # Timestamps y limpieza
    uploaded_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    auto_delete_at = Column(DateTime, nullable=True, index=True)

    # Relaciones
    ticket = relationship('Ticket', back_populates='attachments')
    uploaded_by = relationship('User', foreign_keys=[uploaded_by_id])
    comment = relationship('Comment', back_populates='attachments', foreign_keys=[comment_id])

    __table_args__ = (
        Index('ix_helpdesk_attachment_auto_delete', 'auto_delete_at'),
        Index('ix_helpdesk_attachment_type', 'attachment_type'),
    )

    def __repr__(self):
        return f'<Attachment {self.original_filename} on Ticket#{self.ticket_id}>'

    @property
    def full_path(self):
        """Ruta absoluta del archivo"""
        upload_folder = os.getenv('HELPDESK_UPLOAD_PATH', '/var/uploads/helpdesk')
        return os.path.join(upload_folder, self.filepath)

    @property
    def should_be_deleted(self):
        """Verifica si ya pasó la fecha de auto-eliminación"""
        if not self.auto_delete_at:
            return False
        return datetime.now() >= self.auto_delete_at

    def set_auto_delete(self, days=7):
        """Establece la fecha de auto-eliminación (llamar cuando se resuelve el ticket)"""
        self.auto_delete_at = datetime.now() + timedelta(days=days)

    def to_dict(self):
        return {
            'id': self.id,
            'ticket_id': self.ticket_id,
            'attachment_type': self.attachment_type,
            'comment_id': self.comment_id,
            'filename': self.filename,
            'original_filename': self.original_filename,
            'mime_type': self.mime_type,
            'file_size': self.file_size,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'uploaded_by': {
                'id': self.uploaded_by.id,
                'name': self.uploaded_by.full_name,
                'username': self.uploaded_by.username,
            } if self.uploaded_by else None,
        }
