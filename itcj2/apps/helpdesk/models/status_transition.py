"""
Modelo para las transiciones válidas entre estados de ticket (editable desde la UI).
Reemplaza el dict hardcoded `valid_transitions` en ticket_service.py.
"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class StatusTransition(Base):
    """
    Transición permitida de un estado a otro.
    Cada fila representa un arco válido en el grafo de estados del ticket.
    El par (from_status_id, to_status_id) debe ser único.
    """
    __tablename__ = 'helpdesk_status_transition'

    id = Column(Integer, primary_key=True)

    # --- Foreign Keys ---
    from_status_id = Column(
        Integer,
        ForeignKey('helpdesk_ticket_status.id', ondelete='CASCADE'),
        nullable=False,
    )
    to_status_id = Column(
        Integer,
        ForeignKey('helpdesk_ticket_status.id', ondelete='CASCADE'),
        nullable=False,
    )

    # --- Reglas de transición ---
    required_perm = Column(String(100), nullable=True)
    # permiso requerido para ejecutar esta transición, ej: helpdesk.ticket.close
    required_fields = Column(JSON, nullable=True)
    # lista de campos obligatorios al hacer la transición,
    # ej: ["resolution_notes", "time_invested_minutes"]

    # --- Auditoría ---
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, server_default=text("NOW()"))

    # --- Relaciones ---
    from_status = relationship('TicketStatus', foreign_keys=[from_status_id])
    to_status = relationship('TicketStatus', foreign_keys=[to_status_id])

    # --- Índices y constraints compuestos ---
    __table_args__ = (
        UniqueConstraint('from_status_id', 'to_status_id', name='uq_status_transition'),
        Index('ix_status_transition_from', 'from_status_id', 'is_active'),
    )

    def __repr__(self):
        return (
            f'<StatusTransition from={self.from_status_id} to={self.to_status_id}'
            f' active={self.is_active}>'
        )

    def to_dict(self, include_status_codes: bool = False):
        data = {
            'id': self.id,
            'from_status_id': self.from_status_id,
            'to_status_id': self.to_status_id,
            'required_perm': self.required_perm,
            'required_fields': self.required_fields,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_status_codes:
            data['from_code'] = self.from_status.code if self.from_status else None
            data['from_label'] = self.from_status.label if self.from_status else None
            data['to_code'] = self.to_status.code if self.to_status else None
            data['to_label'] = self.to_status.label if self.to_status else None
        return data
