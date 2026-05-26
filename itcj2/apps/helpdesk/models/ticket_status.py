"""
Modelo para el catálogo de estados de tickets (editable desde la UI).
Reemplaza el dict hardcoded `progress_stages` en ticket.py.
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import text

from itcj2.models.base import Base


class TicketStatus(Base):
    """
    Catálogo de estados de ticket con metadatos de presentación y flujo.
    Flujo canónico: PENDING → ASSIGNED → IN_PROGRESS → RESOLVED_* → CLOSED
    Los estados terminales (is_terminal=True) no admiten ninguna transición saliente.
    """
    __tablename__ = 'helpdesk_ticket_status'

    id = Column(Integer, primary_key=True)

    # --- Identificación ---
    code = Column(String(30), nullable=False, unique=True, index=True)
    # Valores canónicos: PENDING | ASSIGNED | IN_PROGRESS |
    #                    RESOLVED_SUCCESS | RESOLVED_FAILED | CLOSED | CANCELED
    label = Column(String(60), nullable=False)

    # --- Presentación ---
    color = Column(String(20), nullable=True)        # hex o nombre CSS, ej: #6c757d
    badge_class = Column(String(80), nullable=True)  # clase Bootstrap, ej: bg-warning text-dark
    icon = Column(String(60), nullable=True)         # nombre de ícono, ej: fa-clock

    # --- Progreso y etapa ---
    progress_pct = Column(Integer, default=0, nullable=False)  # 0–100
    stage = Column(String(20), nullable=False)
    # Valores: created | assigned | working | resolved | closed | canceled

    # --- Flags de comportamiento ---
    is_open = Column(Boolean, default=True, nullable=False)
    is_resolved = Column(Boolean, default=False, nullable=False)
    is_terminal = Column(Boolean, default=False, nullable=False)

    # --- Ordenamiento ---
    display_order = Column(Integer, default=0)

    # --- Auditoría ---
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, server_default=text("NOW()"))

    def __repr__(self):
        return f'<TicketStatus {self.code} stage={self.stage} progress={self.progress_pct}>'

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'label': self.label,
            'color': self.color,
            'badge_class': self.badge_class,
            'icon': self.icon,
            'progress_pct': self.progress_pct,
            'stage': self.stage,
            'is_open': self.is_open,
            'is_resolved': self.is_resolved,
            'is_terminal': self.is_terminal,
            'display_order': self.display_order,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
