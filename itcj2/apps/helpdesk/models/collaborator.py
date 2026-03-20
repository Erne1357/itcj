from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class TicketCollaborator(Base):
    """
    Registro de colaboradores en un ticket.
    Permite rastrear múltiples personas que trabajaron en la resolución.
    """
    __tablename__ = 'helpdesk_ticket_collaborator'

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey('helpdesk_ticket.id'), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False, index=True)

    # Rol simbólico en la colaboración (no es un rol real del sistema)
    collaboration_role = Column(String(20), nullable=False)
    # Valores válidos: 'LEAD', 'SUPERVISOR', 'COLLABORATOR', 'TRAINEE', 'CONSULTANT'

    # Tiempo invertido por este colaborador (opcional)
    time_invested_minutes = Column(Integer, nullable=True)

    # Notas específicas de este colaborador (opcional)
    notes = Column(Text, nullable=True)

    # Metadata
    added_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    added_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)

    # Relaciones
    ticket = relationship('Ticket', back_populates='collaborators')
    user = relationship('User', foreign_keys=[user_id], backref='ticket_collaborations')
    added_by = relationship('User', foreign_keys=[added_by_id])

    __table_args__ = (
        UniqueConstraint('ticket_id', 'user_id', name='uq_ticket_user_collaboration'),
        Index('ix_helpdesk_collaborator_ticket', 'ticket_id'),
        Index('ix_helpdesk_collaborator_user', 'user_id'),
    )

    VALID_ROLES = ['LEAD', 'SUPERVISOR', 'COLLABORATOR', 'TRAINEE', 'CONSULTANT']

    def __repr__(self):
        return f'<TicketCollaborator Ticket#{self.ticket_id} User#{self.user_id} {self.collaboration_role}>'

    def to_dict(self):
        return {
            'id': self.id,
            'ticket_id': self.ticket_id,
            'user': {
                'id': self.user.id,
                'name': self.user.full_name,
                'username': self.user.username or self.user.control_number,
            } if self.user else None,
            'collaboration_role': self.collaboration_role,
            'time_invested_minutes': self.time_invested_minutes,
            'notes': self.notes,
            'added_at': self.added_at.isoformat() if self.added_at else None,
            'added_by': {
                'id': self.added_by.id,
                'name': self.added_by.full_name,
            } if self.added_by else None,
        }

    @staticmethod
    def validate_role(role):
        """Valida que el rol sea válido"""
        if role not in TicketCollaborator.VALID_ROLES:
            raise ValueError(f"Rol inválido. Debe ser uno de: {', '.join(TicketCollaborator.VALID_ROLES)}")
        return True
