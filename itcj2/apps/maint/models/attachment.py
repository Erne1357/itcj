from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class MaintAttachment(Base):
    """
    Archivos adjuntos de tickets de mantenimiento.

    attachment_type: 'ticket' | 'resolution' | 'comment'

    Ciclo de purga: cuando el archivo físico se elimina del disco, is_purged=True
    y filepath se pone NULL, pero la fila se conserva para trazabilidad.
    """
    __tablename__ = 'maint_attachments'

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey('maint_tickets.id'), nullable=False)
    uploaded_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)
    attachment_type = Column(String(30), nullable=False)
    comment_id = Column(Integer, ForeignKey('maint_comments.id'), nullable=True)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    filepath = Column(String(500), nullable=True)   # NULL cuando is_purged=True
    mime_type = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    auto_delete_at = Column(DateTime, nullable=True)  # 2 días tras resolución

    # --- Purga de archivo físico (preserva la fila) ---
    is_purged = Column(Boolean, nullable=False, server_default=text("FALSE"))
    purged_at = Column(DateTime, nullable=True)

    # Relaciones
    ticket = relationship('MaintTicket', back_populates='attachments',
                          foreign_keys=[ticket_id])
    uploaded_by = relationship('User', foreign_keys=[uploaded_by_id])
    comment = relationship('MaintComment', back_populates='attachments',
                           foreign_keys=[comment_id])

    __table_args__ = (
        Index('ix_maint_attachment_auto_delete', 'auto_delete_at'),
        Index('ix_maint_attachment_ticket_type', 'ticket_id', 'attachment_type'),
        Index('ix_maint_attachment_purged', 'is_purged', 'auto_delete_at'),
    )

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
            'is_purged': self.is_purged,
            'purged_at': self.purged_at.isoformat() if self.purged_at else None,
            # filepath omitido intencionalmente — no exponer rutas del sistema de archivos
        }
