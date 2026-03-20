from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class Ticket(Base):
    """
    Modelo principal de tickets.
    Flujo: PENDING → ASSIGNED → IN_PROGRESS → RESOLVED_SUCCESS/RESOLVED_FAILED → CLOSED
    """
    __tablename__ = 'helpdesk_ticket'

    id = Column(Integer, primary_key=True)
    ticket_number = Column(String(20), unique=True, nullable=False, index=True)

    # ==================== SOLICITANTE ====================
    requester_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False, index=True)
    requester_department_id = Column(Integer, ForeignKey('core_departments.id'), nullable=True)

    # ==================== CLASIFICACIÓN ====================
    area = Column(String(20), nullable=False, index=True)  # 'DESARROLLO' | 'SOPORTE'
    category_id = Column(Integer, ForeignKey('helpdesk_category.id'), nullable=False)
    priority = Column(String(20), nullable=False, default='MEDIA')

    # ==================== CONTENIDO ====================
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    location = Column(String(200), nullable=True)
    office_document_folio = Column(String(50), nullable=True)
    custom_fields = Column(JSON, nullable=True)

    # ==================== ESTADO Y ASIGNACIÓN ====================
    status = Column(String(30), nullable=False, default='PENDING', index=True)

    assigned_to_user_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True, index=True)
    assigned_to_team = Column(String(50), nullable=True)

    # ==================== RESOLUCIÓN ====================
    resolution_notes = Column(Text, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=True)

    # ==================== CALIFICACIÓN ====================
    rating_attention = Column(Integer, nullable=True)
    rating_speed = Column(Integer, nullable=True)
    rating_efficiency = Column(Boolean, nullable=True)
    rating_comment = Column(Text, nullable=True)
    rated_at = Column(DateTime, nullable=True)

    # ==================== TIMESTAMPS ====================
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"), index=True)
    created_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_by_id = Column(BigInteger, ForeignKey('core_users.id'), nullable=False)
    closed_at = Column(DateTime, nullable=True)

    # ==================== TIEMPOS ====================
    time_invested_minutes = Column(Integer, nullable=True)

    # ==================== CAMPOS DE MANTENIMIENTO ====================
    maintenance_type = Column(String(20), nullable=True)  # 'PREVENTIVO' | 'CORRECTIVO'
    service_origin = Column(String(20), nullable=True)    # 'INTERNO' | 'EXTERNO'
    observations = Column(Text, nullable=True)

    # ==================== RELACIONES ====================
    requester = relationship('User', foreign_keys=[requester_id], back_populates='tickets_requested')
    assigned_to = relationship('User', foreign_keys=[assigned_to_user_id], back_populates='tickets_assigned')
    resolved_by = relationship('User', foreign_keys=[resolved_by_id], back_populates='tickets_resolved')
    created_by_user = relationship('User', foreign_keys=[created_by_id], back_populates='tickets_created')
    updated_by_user = relationship('User', foreign_keys=[updated_by_id], back_populates='tickets_updated')
    requester_department = relationship('Department', foreign_keys=[requester_department_id])
    category = relationship('Category', back_populates='tickets')

    assignments = relationship('Assignment', back_populates='ticket', cascade='all, delete-orphan', lazy='dynamic')
    comments = relationship('Comment', back_populates='ticket', cascade='all, delete-orphan', lazy='dynamic')
    attachments = relationship('Attachment', back_populates='ticket', cascade='all, delete-orphan', lazy='dynamic')
    status_logs = relationship('StatusLog', back_populates='ticket', cascade='all, delete-orphan', lazy='dynamic')
    collaborators = relationship(
        'TicketCollaborator',
        back_populates='ticket',
        cascade='all, delete-orphan',
        lazy='dynamic',
        order_by='TicketCollaborator.added_at',
    )
    ticket_items = relationship(
        "TicketInventoryItem",
        back_populates="ticket",
        cascade="all, delete-orphan",
        lazy='dynamic',
    )

    # ==================== ÍNDICES COMPUESTOS ====================
    __table_args__ = (
        Index('ix_helpdesk_ticket_status_priority', 'status', 'priority'),
        Index('ix_helpdesk_ticket_assigned_status', 'assigned_to_user_id', 'status'),
        Index('ix_helpdesk_ticket_area_status', 'area', 'status'),
        Index('ix_helpdesk_ticket_requester_status', 'requester_id', 'status'),
    )

    def __repr__(self):
        return f'<Ticket {self.ticket_number}: {self.title[:30]}>'

    @property
    def is_open(self):
        return self.status not in ['CLOSED', 'CANCELED']

    @property
    def is_resolved(self):
        return self.status in ['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED']

    @property
    def can_be_rated(self):
        return self.is_resolved and self.rating_attention is None

    @property
    def resolution_time_hours(self):
        if not self.resolved_at:
            return None
        delta = self.resolved_at - self.created_at
        return delta.total_seconds() / 3600

    @property
    def time_invested_hours(self):
        if not self.time_invested_minutes:
            return None
        return self.time_invested_minutes / 60

    @property
    def business_hours_elapsed(self):
        """
        Tiempo en horario laboral (8 AM - 6 PM, Lun-Vie)
        Excluye noches y fines de semana.
        """
        if not self.resolved_at:
            return None
        from itcj2.apps.helpdesk.utils.time_calculator import calculate_business_hours
        from itcj2.apps.helpdesk.utils.timezone_utils import ensure_local_timezone
        created_at = ensure_local_timezone(self.created_at)
        resolved_at = ensure_local_timezone(self.resolved_at)
        return calculate_business_hours(created_at, resolved_at)

    @property
    def inventory_items(self):
        """Lista de equipos relacionados con el ticket"""
        return [ti.inventory_item for ti in self.ticket_items if ti.inventory_item]

    @property
    def inventory_items_count(self):
        return self.ticket_items.count()

    def to_dict(self, include_relations=False, include_metrics=False):
        data = {
            'id': self.id,
            'ticket_number': self.ticket_number,
            'title': self.title,
            'description': self.description,
            'location': self.location,
            'area': self.area,
            'priority': self.priority,
            'status': self.status,
            'office_document_folio': self.office_document_folio,
            'custom_fields': self.custom_fields,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'created_by_id': self.created_by_id,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'updated_by_id': self.updated_by_id,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'rated_at': self.rated_at.isoformat() if self.rated_at else None,
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'rating_attention': self.rating_attention,
            'rating_speed': self.rating_speed,
            'rating_efficiency': self.rating_efficiency,
            'rating_comment': self.rating_comment,
            'resolution_notes': self.resolution_notes,
            'resolved_by': self.resolved_by.to_dict() if self.resolved_by else None,
            'time_invested_minutes': self.time_invested_minutes,
            'maintenance_type': self.maintenance_type,
            'service_origin': self.service_origin,
            'observations': self.observations,
        }

        if include_relations:
            data.update({
                'requester': {
                    'id': self.requester.id,
                    'name': self.requester.full_name,
                    'email': self.requester.email,
                    'username': self.requester.username or self.requester.control_number,
                } if self.requester else None,
                'category': self.category.to_dict() if self.category else None,
                'assigned_to': {
                    'id': self.assigned_to.id,
                    'name': self.assigned_to.full_name,
                    'username': self.assigned_to.username or self.assigned_to.control_number,
                } if self.assigned_to else None,
                'assigned_to_team': self.assigned_to_team,
                'requester_department': {
                    'id': self.requester_department.id,
                    'name': self.requester_department.name,
                } if self.requester_department else None,
                'created_by': {
                    'id': self.created_by_user.id,
                    'name': self.created_by_user.full_name,
                    'username': self.created_by_user.username or self.created_by_user.control_number,
                } if self.created_by_user else None,
                'updated_by': {
                    'id': self.updated_by_user.id,
                    'name': self.updated_by_user.full_name,
                    'username': self.updated_by_user.username or self.updated_by_user.control_number,
                } if self.updated_by_user else None,
                'collaborators': [c.to_dict() for c in self.collaborators] if hasattr(self, 'collaborators') else [],
                'collaborators_count': self.collaborators.count() if hasattr(self, 'collaborators') else 0,
                'inventory_items': [
                    {
                        'id': item.id,
                        'inventory_number': item.inventory_number,
                        'display_name': item.display_name,
                        'brand': item.brand,
                        'model': item.model,
                        'location_detail': item.location_detail,
                        'category': {
                            'id': item.category.id,
                            'name': item.category.name,
                            'icon': item.category.icon,
                        } if item.category else None,
                        'assigned_to_user': {
                            'id': item.assigned_to_user.id,
                            'full_name': item.assigned_to_user.full_name,
                        } if item.assigned_to_user else None,
                        'group': {
                            'id': item.group.id,
                            'name': item.group.name,
                            'code': item.group.code,
                        } if item.group else None,
                    }
                    for item in self.inventory_items
                ] if self.inventory_items else [],
                'inventory_items_count': self.inventory_items_count,
            })
            # Alias para compatibilidad
            if data.get('inventory_items'):
                data['inventory_item'] = data['inventory_items'][0] if len(data['inventory_items']) == 1 else None
            else:
                data['inventory_item'] = None

        if include_metrics:
            from itcj2.apps.helpdesk.utils.timezone_utils import now_local, ensure_local_timezone

            created_at = ensure_local_timezone(self.created_at)
            end_time = ensure_local_timezone(self.resolved_at) if self.resolved_at else now_local()
            total_elapsed_hours = (end_time - created_at).total_seconds() / 3600

            sla_targets = {'URGENTE': 4, 'ALTA': 24, 'MEDIA': 72, 'BAJA': 168}
            sla_target_hours = sla_targets.get(self.priority, 72)
            sla_percentage = min((total_elapsed_hours / sla_target_hours) * 100, 100) if sla_target_hours > 0 else 0
            sla_status = 'on_time' if total_elapsed_hours <= sla_target_hours else 'overdue'

            progress_stages = {
                'PENDING': {'stage': 'created', 'progress': 10, 'description': 'Ticket creado'},
                'ASSIGNED': {'stage': 'assigned', 'progress': 30, 'description': 'Asignado a técnico'},
                'IN_PROGRESS': {'stage': 'working', 'progress': 60, 'description': 'En proceso de resolución'},
                'RESOLVED_SUCCESS': {'stage': 'resolved', 'progress': 90, 'description': 'Resuelto exitosamente'},
                'RESOLVED_FAILED': {'stage': 'resolved', 'progress': 85, 'description': 'Atendido pero no resuelto'},
                'CLOSED': {'stage': 'closed', 'progress': 100, 'description': 'Cerrado'},
                'CANCELED': {'stage': 'canceled', 'progress': 0, 'description': 'Cancelado'},
            }
            current_progress = progress_stages.get(
                self.status,
                {'stage': 'unknown', 'progress': 0, 'description': 'Estado desconocido'},
            )

            rating_avg = None
            if self.rating_attention is not None and self.rating_speed is not None:
                rating_avg = round((self.rating_attention + self.rating_speed) / 2, 1)

            data.update({
                'metrics': {
                    'total_elapsed_hours': round(total_elapsed_hours, 2),
                    'resolution_time_hours': self.resolution_time_hours,
                    'time_invested_hours': self.time_invested_hours,
                    'business_hours_elapsed': self.business_hours_elapsed,
                    'sla': {
                        'target_hours': sla_target_hours,
                        'elapsed_hours': round(total_elapsed_hours, 2),
                        'percentage': round(sla_percentage, 1),
                        'status': sla_status,
                        'remaining_hours': max(0, sla_target_hours - total_elapsed_hours) if sla_status == 'on_time' else 0,
                    },
                    'progress': {
                        'current_stage': current_progress['stage'],
                        'percentage': current_progress['progress'],
                        'description': current_progress['description'],
                        'is_open': self.is_open,
                        'is_resolved': self.is_resolved,
                        'can_be_rated': self.can_be_rated,
                    },
                    'quality': {
                        'has_rating': self.rating_attention is not None,
                        'rating_attention': self.rating_attention,
                        'rating_speed': self.rating_speed,
                        'rating_efficiency': self.rating_efficiency,
                        'rating_comment': self.rating_comment,
                        'rating_average': rating_avg,
                        'rating_category': self._get_rating_category(rating_avg),
                        'has_comments': self.comments.count() > 0 if hasattr(self, 'comments') else False,
                        'resolution_quality': self._get_resolution_quality(),
                    },
                },
            })

        return data

    def _get_rating_category(self, rating):
        if rating is None:
            return None
        elif rating >= 5:
            return 'excelente'
        elif rating >= 4:
            return 'bueno'
        elif rating >= 3:
            return 'regular'
        elif rating >= 2:
            return 'malo'
        else:
            return 'muy_malo'

    def _get_resolution_quality(self):
        if not self.is_resolved:
            return None
        if self.status == 'RESOLVED_SUCCESS':
            if self.time_invested_hours and self.time_invested_hours <= 2:
                return 'rapida'
            elif self.time_invested_hours and self.time_invested_hours <= 8:
                return 'normal'
            else:
                return 'lenta'
        elif self.status == 'RESOLVED_FAILED':
            return 'no_resuelto'
        else:
            return 'cerrado'
