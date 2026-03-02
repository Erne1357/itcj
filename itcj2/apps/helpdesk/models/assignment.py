from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class Assignment(Base):
    """
    Historial de asignaciones y reasignaciones de tickets.
    Cada vez que un ticket se asigna/reasigna, se crea un registro aquí.
    """
    __tablename__ = 'helpdesk_assignment'

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey('helpdesk_ticket.id'), nullable=False, index=True)

    # Quién asignó
    assigned_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)

    # A quién/qué se asignó
    assigned_to_user_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)
    assigned_to_team = Column(String(50), nullable=True)

    # Timestamps
    assigned_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    unassigned_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"), onupdate=text("NOW()"))

    # Razón (útil en reasignaciones)
    reason = Column(Text, nullable=True)

    # Relaciones
    ticket = relationship('Ticket', back_populates='assignments')
    assigned_by = relationship('User', foreign_keys=[assigned_by_id])
    assigned_to = relationship('User', foreign_keys=[assigned_to_user_id])

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
                'username': self.assigned_by.username,
            } if self.assigned_by else None,
            'assigned_to': {
                'id': self.assigned_to.id,
                'name': self.assigned_to.full_name,
                'username': self.assigned_to.username,
            } if self.assigned_to else None,
            'assigned_to_team': self.assigned_to_team,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'unassigned_at': self.unassigned_at.isoformat() if self.unassigned_at else None,
            'reason': self.reason,
        }
