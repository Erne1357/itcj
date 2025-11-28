from itcj.core.extensions import db

class StatusLog(db.Model):
    """
    Registro de cambios de estado de tickets (auditoría).
    Cada vez que un ticket cambia de estado, se registra aquí.
    """
    __tablename__ = 'helpdesk_status_log'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('helpdesk_ticket.id'), nullable=False, index=True)
    
    # Estados
    from_status = db.Column(db.String(30), nullable=True)  # NULL si es el primer estado (creación)
    to_status = db.Column(db.String(30), nullable=False)
    
    # Quién cambió el estado
    changed_by_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=False)
    
    # Notas opcionales (ej: razón de cancelación)
    notes = db.Column(db.Text, nullable=True)
    
    # Timestamp
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    
    # Relaciones
    ticket = db.relationship('Ticket', back_populates='status_logs')
    changed_by = db.relationship('User', foreign_keys=[changed_by_id])
    
    # Índice para consultas de timeline
    __table_args__ = (
        db.Index('ix_helpdesk_status_log_ticket_created', 'ticket_id', 'created_at'),
    )
    
    def __repr__(self):
        return f'<StatusLog Ticket#{self.ticket_id}: {self.from_status} → {self.to_status}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'ticket_id': self.ticket_id,
            'from_status': self.from_status,
            'to_status': self.to_status,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'changed_by': {
                'id': self.changed_by.id,
                'name': self.changed_by.full_name,
                'username': self.changed_by.username
            } if self.changed_by else None
        }