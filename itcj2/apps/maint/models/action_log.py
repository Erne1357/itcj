from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class MaintTicketActionLog(Base):
    """
    Auditoría reforzada: registra TODA acción sobre el ticket.

    Valores de action:
        CREATED                   — Ticket creado
        TECHNICIAN_ASSIGNED       — Técnico asignado
        TECHNICIAN_UNASSIGNED     — Técnico removido
        STATUS_CHANGED            — Cambio de estado
        RESOLVED_BY_ASSIGNED      — Resuelto por técnico formalmente asignado
        RESOLVED_BY_DISPATCHER    — Resuelto por dispatcher NO asignado al ticket
        RATED                     — Calificado por el solicitante
        COMMENTED                 — Comentario agregado
        ATTACHMENT_ADDED          — Archivo adjunto
        EDITED                    — Campo editado (antes de asignación)
        CANCELED                  — Cancelado
        WAREHOUSE_MATERIAL_ADDED  — Material del almacén registrado
        WAREHOUSE_MATERIAL_REMOVED — Material del almacén revertido
    """
    __tablename__ = 'maint_ticket_action_logs'

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey('maint_tickets.id'), nullable=False)
    action = Column(String(60), nullable=False)
    performed_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)
    performed_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    detail = Column(JSON, nullable=True)
    # Contexto por acción:
    # TECHNICIAN_ASSIGNED:    {user_id, user_name, assigned_by}
    # RESOLVED_BY_DISPATCHER: {resolver_id, resolver_name, had_active_technicians: bool, active_technician_ids: [...]}
    # EDITED:                 {field, old_value, new_value}
    # STATUS_CHANGED:         {from_status, to_status}

    # Relaciones
    ticket = relationship('MaintTicket', back_populates='action_logs')
    performed_by = relationship('User', foreign_keys=[performed_by_id])

    __table_args__ = (
        Index('ix_maint_action_log_ticket_date', 'ticket_id', 'performed_at'),
        Index('ix_maint_action_log_user_date', 'performed_by_id', 'performed_at'),
        Index('ix_maint_action_log_action_date', 'action', 'performed_at'),
    )
