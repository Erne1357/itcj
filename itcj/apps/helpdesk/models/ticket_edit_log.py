from itcj.core.extensions import db


class TicketEditLog(db.Model):
    """
    Registro de ediciones de campos de tickets (auditoria).
    Registra cambios en campos distintos al status (area, categoria, prioridad, titulo, etc.)
    realizados antes de la asignacion del ticket.
    """
    __tablename__ = 'helpdesk_ticket_edit_log'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('helpdesk_ticket.id'), nullable=False, index=True)

    # Campo modificado: 'area', 'category_id', 'priority', 'title', 'description', 'location', 'custom_fields'
    field_name = db.Column(db.String(50), nullable=False)

    # Valores (como texto para almacenar cualquier tipo)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)

    # Quien hizo el cambio
    changed_by_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=False)

    # Timestamp
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))

    # ==================== RELACIONES ====================
    ticket = db.relationship('Ticket', backref=db.backref('edit_logs', lazy='dynamic', cascade='all, delete-orphan'))
    changed_by = db.relationship('User', foreign_keys=[changed_by_id])

    # ==================== INDICES ====================
    __table_args__ = (
        db.Index('ix_helpdesk_ticket_edit_log_ticket_created', 'ticket_id', 'created_at'),
    )

    def to_dict(self):
        """Serializa el registro para respuestas JSON"""
        return {
            'id': self.id,
            'ticket_id': self.ticket_id,
            'field_name': self.field_name,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'changed_by': {
                'id': self.changed_by.id,
                'name': self.changed_by.full_name
            } if self.changed_by else None
        }

    def __repr__(self):
        return f'<TicketEditLog {self.id}: ticket={self.ticket_id} field={self.field_name}>'
