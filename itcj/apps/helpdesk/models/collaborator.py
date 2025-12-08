from itcj.core.extensions import db
from datetime import datetime

class TicketCollaborator(db.Model):
    """
    Registro de colaboradores en un ticket.
    Permite rastrear múltiples personas que trabajaron en la resolución.
    """
    __tablename__ = 'helpdesk_ticket_collaborator'
    
    # ==================== CAMPOS ====================
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('helpdesk_ticket.id'), nullable=False, index=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=False, index=True)
    
    # Rol en la colaboración (simbólico, NO es un rol real del sistema)
    collaboration_role = db.Column(db.String(20), nullable=False)
    # Valores válidos: 'LEAD', 'SUPERVISOR', 'COLLABORATOR', 'TRAINEE', 'CONSULTANT'
    
    # Tiempo invertido por este colaborador (opcional)
    time_invested_minutes = db.Column(db.Integer, nullable=True)
    
    # Notas específicas de este colaborador (opcional)
    notes = db.Column(db.Text, nullable=True)
    
    # Metadata
    added_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    added_by_id = db.Column(db.BigInteger, db.ForeignKey('core_users.id'), nullable=True)
    
    # ==================== RELACIONES ====================
    ticket = db.relationship('Ticket', back_populates='collaborators')
    user = db.relationship('User', foreign_keys=[user_id], backref='ticket_collaborations')
    added_by = db.relationship('User', foreign_keys=[added_by_id])
    
    # ==================== CONSTRAINTS ====================
    __table_args__ = (
        # Un usuario solo puede ser colaborador UNA vez por ticket
        db.UniqueConstraint('ticket_id', 'user_id', name='uq_ticket_user_collaboration'),
        db.Index('ix_helpdesk_collaborator_ticket', 'ticket_id'),
        db.Index('ix_helpdesk_collaborator_user', 'user_id'),
    )
    
    # ==================== VALIDACIONES ====================
    VALID_ROLES = ['LEAD', 'SUPERVISOR', 'COLLABORATOR', 'TRAINEE', 'CONSULTANT']
    
    def __repr__(self):
        return f'<TicketCollaborator Ticket#{self.ticket_id} User#{self.user_id} {self.collaboration_role}>'
    
    def to_dict(self):
        """Serialización para API"""
        return {
            'id': self.id,
            'ticket_id': self.ticket_id,
            'user': {
                'id': self.user.id,
                'name': self.user.full_name,
                'username': self.user.username or self.user.control_number
            } if self.user else None,
            'collaboration_role': self.collaboration_role,
            'time_invested_minutes': self.time_invested_minutes,
            'notes': self.notes,
            'added_at': self.added_at.isoformat() if self.added_at else None,
            'added_by': {
                'id': self.added_by.id,
                'name': self.added_by.full_name
            } if self.added_by else None
        }
    
    @staticmethod
    def validate_role(role):
        """Valida que el rol sea válido"""
        if role not in TicketCollaborator.VALID_ROLES:
            raise ValueError(f"Rol inválido. Debe ser uno de: {', '.join(TicketCollaborator.VALID_ROLES)}")
        return True