from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


# Horas de SLA por prioridad (para calcular due_at al crear el ticket)
SLA_HOURS: dict[str, int] = {
    'URGENTE': 2,
    'ALTA': 24,
    'MEDIA': 72,
    'BAJA': 168,
}


class MaintTicket(Base):
    """
    Ticket de mantenimiento.

    Flujo de estados:
        PENDING → ASSIGNED → IN_PROGRESS → RESOLVED_SUCCESS | RESOLVED_FAILED → CLOSED
        En cualquier momento antes de RESOLVED → CANCELED

    Diferencias clave vs Helpdesk:
        - Asignación múltiple de técnicos (1..N)
        - Dispatcher puede resolver sin estar asignado (RESOLVED_BY_DISPATCHER)
        - Auditoría reforzada con MaintTicketActionLog
        - due_at calculado al crear según prioridad (SLA_HOURS)
    """
    __tablename__ = 'maint_tickets'

    id = Column(Integer, primary_key=True)
    ticket_number = Column(String(20), unique=True, nullable=False)
    # Formato: MANT-{YEAR}-{SEQ:06d}  ej: MANT-2026-000001

    # ==================== SOLICITANTE ====================
    requester_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)
    requester_department_id = Column(Integer, ForeignKey('core_departments.id'), nullable=False)

    # ==================== CLASIFICACIÓN ====================
    category_id = Column(Integer, ForeignKey('maint_categories.id'), nullable=False)
    priority = Column(String(20), nullable=False, default='MEDIA')
    # Valores: BAJA | MEDIA | ALTA | URGENTE

    # ==================== CONTENIDO ====================
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    location = Column(String(300), nullable=True)
    custom_fields = Column(JSON, nullable=True)   # Campos del field_template de la categoría

    # ==================== ESTADO ====================
    status = Column(String(30), nullable=False, default='PENDING')
    # Valores: PENDING | ASSIGNED | IN_PROGRESS |
    #          RESOLVED_SUCCESS | RESOLVED_FAILED | CLOSED | CANCELED

    # ==================== SLA ====================
    due_at = Column(DateTime, nullable=True)
    # Calculado al crear: created_at + SLA_HOURS[priority] horas
    # Permite alertas de vencimiento y reportes de cumplimiento

    # ==================== RESOLUCIÓN ====================
    maintenance_type = Column(String(20), nullable=True)   # PREVENTIVO | CORRECTIVO
    service_origin = Column(String(20), nullable=True)     # INTERNO | EXTERNO
    resolution_notes = Column(Text, nullable=True)
    time_invested_minutes = Column(Integer, nullable=True)
    observations = Column(Text, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)

    # ==================== CALIFICACIÓN ====================
    rating_attention = Column(Integer, nullable=True)      # 1–5
    rating_speed = Column(Integer, nullable=True)          # 1–5
    rating_efficiency = Column(Boolean, nullable=True)
    rating_comment = Column(Text, nullable=True)
    rated_at = Column(DateTime, nullable=True)

    # ==================== AUDITORÍA ====================
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    created_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"),
                        onupdate=text("NOW()"))
    updated_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)
    closed_at = Column(DateTime, nullable=True)
    canceled_at = Column(DateTime, nullable=True)
    canceled_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)
    cancel_reason = Column(Text, nullable=True)

    # ==================== RELACIONES ====================
    requester = relationship('User', foreign_keys=[requester_id])
    requester_department = relationship('Department', foreign_keys=[requester_department_id])
    category = relationship('MaintCategory', back_populates='tickets')
    resolved_by = relationship('User', foreign_keys=[resolved_by_id])
    created_by_user = relationship('User', foreign_keys=[created_by_id])
    updated_by_user = relationship('User', foreign_keys=[updated_by_id])
    canceled_by_user = relationship('User', foreign_keys=[canceled_by_id])

    technicians = relationship('MaintTicketTechnician', back_populates='ticket',
                               cascade='all, delete-orphan')
    status_logs = relationship('MaintStatusLog', back_populates='ticket',
                               cascade='all, delete-orphan')
    action_logs = relationship('MaintTicketActionLog', back_populates='ticket',
                               cascade='all, delete-orphan')
    comments = relationship('MaintComment', back_populates='ticket',
                            cascade='all, delete-orphan')
    attachments = relationship('MaintAttachment', back_populates='ticket',
                               foreign_keys='MaintAttachment.ticket_id',
                               cascade='all, delete-orphan')

    __table_args__ = (
        Index('ix_maint_tickets_status_created', 'status', 'created_at'),
        Index('ix_maint_tickets_requester_status', 'requester_id', 'status'),
        Index('ix_maint_tickets_number', 'ticket_number'),
        Index('ix_maint_tickets_category_status', 'category_id', 'status'),
        Index('ix_maint_tickets_resolved_by', 'resolved_by_id'),
        Index('ix_maint_tickets_due_at', 'due_at'),
    )

    # ==================== PROPIEDADES CALCULADAS ====================

    @property
    def is_open(self) -> bool:
        return self.status not in ('CLOSED', 'CANCELED')

    @property
    def is_resolved(self) -> bool:
        return self.status in ('RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED')

    @property
    def can_be_rated(self) -> bool:
        return self.is_resolved and self.rating_attention is None

    @property
    def active_technicians(self) -> list:
        """Técnicos con asignación activa (unassigned_at IS NULL)."""
        return [t for t in self.technicians if t.unassigned_at is None]

    @property
    def progress_pct(self) -> int:
        """Porcentaje de avance visual para la UI."""
        return {
            'PENDING': 10,
            'ASSIGNED': 30,
            'IN_PROGRESS': 60,
            'RESOLVED_SUCCESS': 90,
            'RESOLVED_FAILED': 85,
            'CLOSED': 100,
            'CANCELED': 0,
        }.get(self.status, 0)
