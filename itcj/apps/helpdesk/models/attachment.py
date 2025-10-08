from itcj.core.extensions import db
from datetime import datetime, timedelta
import os

class Attachment(db.Model):
    """
    Archivos adjuntos a tickets (solo imágenes).
    Se auto-eliminan X días después de que el ticket se resuelve.
    """
    __tablename__ = 'helpdesk_attachment'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('helpdesk_ticket.id'), nullable=False, index=True)
    uploaded_by_id = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=False)
    
    # Información del archivo
    filename = db.Column(db.String(255), nullable=False)  # Nombre generado (único)
    original_filename = db.Column(db.String(255), nullable=False)  # Nombre original del usuario
    filepath = db.Column(db.String(500), nullable=False)  # Ruta relativa desde UPLOAD_FOLDER
    mime_type = db.Column(db.String(100), nullable=True)  # 'image/png', 'image/jpeg', etc.
    file_size = db.Column(db.Integer, nullable=True)  # Tamaño en bytes
    
    # Timestamps y limpieza
    uploaded_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    auto_delete_at = db.Column(db.DateTime, nullable=True, index=True)  # Se setea cuando el ticket se resuelve
    
    # Relaciones
    ticket = db.relationship('Ticket', back_populates='attachments')
    uploaded_by = db.relationship('User', foreign_keys=[uploaded_by_id])
    
    # Índice para la limpieza automática
    __table_args__ = (
        db.Index('ix_helpdesk_attachment_auto_delete', 'auto_delete_at'),
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
            'filename': self.filename,
            'original_filename': self.original_filename,
            'mime_type': self.mime_type,
            'file_size': self.file_size,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'uploaded_by': {
                'id': self.uploaded_by.id,
                'name': self.uploaded_by.name,
                'username': self.uploaded_by.username
            } if self.uploaded_by else None
        }