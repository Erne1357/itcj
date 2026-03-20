from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class StatusLog(Base):
    """
    Registro de cambios de estado de tickets (auditoría).
    Cada vez que un ticket cambia de estado, se registra aquí.
    """
    __tablename__ = 'helpdesk_status_log'

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey('helpdesk_ticket.id'), nullable=False, index=True)

    # Estados
    from_status = Column(String(30), nullable=True)  # NULL si es el primer estado
    to_status = Column(String(30), nullable=False)

    # Quién cambió el estado
    changed_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)

    # Notas opcionales
    notes = Column(Text, nullable=True)

    # Timestamp
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    # Relaciones
    ticket = relationship('Ticket', back_populates='status_logs')
    changed_by = relationship('User', foreign_keys=[changed_by_id])

    __table_args__ = (
        Index('ix_helpdesk_status_log_ticket_created', 'ticket_id', 'created_at'),
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
                'username': self.changed_by.username,
            } if self.changed_by else None,
        }
