from itcj.core.extensions import db

class Assignment(db.Model):
    """
    Historial de asignaciones y reasignaciones de tickets.
    Cada vez que un ticket se asigna/reasigna, se crea un registro aquí.
    """
    __tablename__ = 'helpdesk_assignment'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('helpdesk_ticket.id'), nullable=False, index=True)
    
    # Quién asignó
    assigned_by_id = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=False)
    
    # A quién/qué se asignó
    assigned_to_user_id = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=True)  # Usuario específico
    assigned_to_team = db.Column(db.String(50), nullable=True)  # O equipo ('desarrollo', 'soporte')
    
    # Timestamps
    assigned_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    unassigned_at = db.Column(db.DateTime, nullable=True)  # Cuando se reasigna
    
    # Razón (útil en reasignaciones)
    reason = db.Column(db.Text, nullable=True)
    
    # Relaciones
    ticket = db.relationship('Ticket', back_populates='assignments')
    assigned_by = db.relationship('User', foreign_keys=[assigned_by_id])
    assigned_to = db.relationship('User', foreign_keys=[assigned_to_user_id])
    
    def __repr__(self):
        target = self.assigned_to.username if self.assigned_to else self.assigned_to_team
        return f'<Assignment Ticket#{self.ticket_id} → {target}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'ticket_id': self.ticket_id,
            'assigned_by': {
                'id': self.assigned_by.id,
                'name': self.assigned_by.full_name,
                'username': self.assigned_by.username
            } if self.assigned_by else None,
            'assigned_to': {
                'id': self.assigned_to.id,
                'name': self.assigned_to.full_name,
                'username': self.assigned_to.username
            } if self.assigned_to else None,
            'assigned_to_team': self.assigned_to_team,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'unassigned_at': self.unassigned_at.isoformat() if self.unassigned_at else None,
            'reason': self.reason
        }