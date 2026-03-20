from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class MaintTicketTechnician(Base):
    """
    Asignaciones múltiples de técnicos por ticket.
    Historial completo: un técnico puede ser asignado, removido y vuelto a asignar.
    La asignación activa se filtra con: unassigned_at IS NULL
    """
    __tablename__ = 'maint_ticket_technicians'

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey('maint_tickets.id'), nullable=False)
    user_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)
    assigned_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)
    assigned_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    unassigned_at = Column(DateTime, nullable=True)
    unassigned_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)
    unassigned_reason = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)

    # Relaciones
    ticket = relationship('MaintTicket', back_populates='technicians')
    user = relationship('User', foreign_keys=[user_id])
    assigned_by = relationship('User', foreign_keys=[assigned_by_id])
    unassigned_by = relationship('User', foreign_keys=[unassigned_by_id])

    __table_args__ = (
        # Sin UNIQUE(ticket_id, user_id) — el mismo técnico puede ser reasignado
        Index('ix_maint_ticket_tech_active', 'ticket_id', 'unassigned_at'),
        Index('ix_maint_ticket_tech_user_active', 'user_id', 'unassigned_at'),
        Index('ix_maint_ticket_tech_history', 'ticket_id', 'assigned_at'),
    )
