from itcj.core.extensions import db

class Ticket(db.Model):
    """
    Modelo principal de tickets.
    Flujo: PENDING → ASSIGNED → IN_PROGRESS → RESOLVED_SUCCESS/RESOLVED_FAILED → CLOSED
    """
    __tablename__ = 'helpdesk_ticket'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(20), unique=True, nullable=False, index=True)  # TK-2025-0001
    
    # ==================== SOLICITANTE ====================
    requester_id = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=False, index=True)
    
    # Departamento (puede ser NULL si el usuario no tiene position)
    # Lo obtendremos de position → department, pero guardamos el ID aquí por rendimiento
    requester_department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    
    # ==================== CLASIFICACIÓN ====================
    area = db.Column(db.String(20), nullable=False, index=True)  # 'DESARROLLO' | 'SOPORTE'
    category_id = db.Column(db.Integer, db.ForeignKey('helpdesk_category.id'), nullable=False)
    priority = db.Column(db.String(20), nullable=False, default='MEDIA')  # 'BAJA', 'MEDIA', 'ALTA', 'URGENTE'
    
    # ==================== CONTENIDO ====================
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(200), nullable=True)  # Ubicación física (opcional)
    office_document_folio = db.Column(db.String(50), nullable=True)  # Folio de oficio (opcional)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey('helpdesk_inventory_items.id'), nullable=True, index=True)  # Ítem de inventario relacionado (opcional)
    # ==================== ESTADO Y ASIGNACIÓN ====================
    status = db.Column(db.String(30), nullable=False, default='PENDING', index=True)
    # Estados posibles:
    # - PENDING: Recién creado, sin asignar
    # - ASSIGNED: Asignado a técnico/equipo
    # - IN_PROGRESS: Técnico trabajando en él
    # - RESOLVED_SUCCESS: Resuelto exitosamente
    # - RESOLVED_FAILED: Atendido pero no resuelto
    # - CLOSED: Cerrado (después de calificación)
    # - CANCELED: Cancelado por el usuario
    
    assigned_to_user_id = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=True, index=True)
    assigned_to_team = db.Column(db.String(50), nullable=True)  # 'desarrollo', 'soporte', NULL
    
    # ==================== RESOLUCIÓN ====================
    resolution_notes = db.Column(db.Text, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by_id = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=True)
    
    # ==================== CALIFICACIÓN ====================
    rating = db.Column(db.Integer, nullable=True)  # 1-5 estrellas
    rating_comment = db.Column(db.Text, nullable=True)
    rated_at = db.Column(db.DateTime, nullable=True)
    
    # ==================== TIMESTAMPS ====================
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"), index=True)
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    closed_at = db.Column(db.DateTime, nullable=True)
    
    # ==================== RELACIONES ====================
    # Usuario que solicita
    requester = db.relationship('User', foreign_keys=[requester_id], backref='tickets_requested')
    
    # Usuario asignado
    assigned_to = db.relationship('User', foreign_keys=[assigned_to_user_id], backref='tickets_assigned')
    
    # Usuario que resolvió
    resolved_by = db.relationship('User', foreign_keys=[resolved_by_id], backref='tickets_resolved')
    
    # Departamento del solicitante
    requester_department = db.relationship('Department', foreign_keys=[requester_department_id])
    
    # Categoría
    category = db.relationship('Category', back_populates='tickets')
    
    # Relaciones en cascada
    assignments = db.relationship('Assignment', back_populates='ticket', cascade='all, delete-orphan', lazy='dynamic')
    comments = db.relationship('Comment', back_populates='ticket', cascade='all, delete-orphan', lazy='dynamic')
    attachments = db.relationship('Attachment', back_populates='ticket', cascade='all, delete-orphan', lazy='dynamic')
    status_logs = db.relationship('StatusLog', back_populates='ticket', cascade='all, delete-orphan', lazy='dynamic')
    
    #Inventario relacionado
    inventory_item = db.relationship('InventoryItem', back_populates='tickets', lazy='joined')

    # ==================== TIEMPOS ====================
    # AUTOMÁTICO: Para métricas de servicio al usuario
    # (Ya definido arriba en TIMESTAMPS)
    resolved_at = db.Column(db.DateTime, nullable=True)
    
    # MANUAL: Para productividad del técnico (opcional pero recomendado)
    time_invested_minutes = db.Column(db.Integer, nullable=True)  # Minutos invertidos por el técnico

    # ==================== ÍNDICES COMPUESTOS ====================
    __table_args__ = (
        db.Index('ix_helpdesk_ticket_status_priority', 'status', 'priority'),
        db.Index('ix_helpdesk_ticket_assigned_status', 'assigned_to_user_id', 'status'),
        db.Index('ix_helpdesk_ticket_area_status', 'area', 'status'),
        db.Index('ix_helpdesk_ticket_requester_status', 'requester_id', 'status'),
    )
    
    def __repr__(self):
        return f'<Ticket {self.ticket_number}: {self.title[:30]}>'
    
    @property
    def is_open(self):
        """Ticket está abierto si no está cerrado ni cancelado"""
        return self.status not in ['CLOSED', 'CANCELED']
    
    @property
    def is_resolved(self):
        """Ticket está resuelto (pero puede no estar cerrado aún)"""
        return self.status in ['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED']
    
    @property
    def can_be_rated(self):
        """Puede ser calificado si está resuelto y no ha sido calificado"""
        return self.is_resolved and self.rating is None
    
    @property
    def resolution_time_hours(self):
        """Tiempo calendario transcurrido (automático)"""
        if not self.resolved_at:
            return None
        delta = self.resolved_at - self.created_at
        return delta.total_seconds() / 3600
    
    @property
    def time_invested_hours(self):
        """Tiempo real invertido por el técnico (manual)"""
        if not self.time_invested_minutes:
            return None
        return self.time_invested_minutes / 60
    
    @property
    def business_hours_elapsed(self):
        """
        Tiempo en horario laboral (8 AM - 6 PM, Lun-Vie)
        Esto excluye noches, fines de semana
        """
        if not self.resolved_at:
            return None
        
        from itcj.apps.helpdesk.utils.time_calculator import calculate_business_hours
        from itcj.apps.helpdesk.utils.timezone_utils import ensure_local_timezone
        
        # Asegurar que las fechas tengan timezone local
        created_at = ensure_local_timezone(self.created_at)
        resolved_at = ensure_local_timezone(self.resolved_at)
        
        return calculate_business_hours(created_at, resolved_at)

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
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'rated_at': self.rated_at.isoformat() if self.rated_at else None,
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'rating': self.rating,
            'rating_comment': self.rating_comment,
            'resolution_notes': self.resolution_notes,
            'time_invested_minutes': self.time_invested_minutes,
        }
        
        if include_relations:
            data.update({
                'requester': {
                    'id': self.requester.id,
                    'name': self.requester.full_name,
                    'username': self.requester.username or self.requester.employee_number
                } if self.requester else None,
                'category': self.category.to_dict() if self.category else None,
                'assigned_to': {
                    'id': self.assigned_to.id,
                    'name': self.assigned_to.full_name,
                    'username': self.assigned_to.username or self.assigned_to.employee_number
                } if self.assigned_to else None,
                'assigned_to_team': self.assigned_to_team,
                'department': {
                    'id': self.requester_department.id,
                    'name': self.requester_department.name
                } if self.requester_department else None,
                'inventory_item': {
                    'id': self.inventory_item.id,
                    'inventory_number': self.inventory_item.inventory_number,
                    'display_name': self.inventory_item.display_name,
                    'brand': self.inventory_item.brand,
                    'model': self.inventory_item.model,
                    'location_detail': self.inventory_item.location_detail,
                } if self.inventory_item else None,
            })
        
        if include_metrics:
            # Calcular métricas temporales
            from itcj.apps.helpdesk.utils.timezone_utils import now_local, ensure_local_timezone
            
            # Asegurar que las fechas tengan timezone local
            created_at = ensure_local_timezone(self.created_at)
            
            # Tiempo transcurrido desde creación hasta ahora (si no está resuelto) o hasta resolución
            if self.resolved_at:
                end_time = ensure_local_timezone(self.resolved_at)
            else:
                end_time = now_local()
            
            total_elapsed_hours = (end_time - created_at).total_seconds() / 3600
            
            # SLA targets (Service Level Agreement) - pueden ser configurables
            sla_targets = {
                'URGENTE': 4,    # 4 horas
                'ALTA': 24,      # 24 horas  
                'MEDIA': 72,     # 72 horas
                'BAJA': 168      # 1 semana
            }
            
            sla_target_hours = sla_targets.get(self.priority, 72)
            sla_percentage = min((total_elapsed_hours / sla_target_hours) * 100, 100) if sla_target_hours > 0 else 0
            sla_status = 'on_time' if total_elapsed_hours <= sla_target_hours else 'overdue'
            
            # Estado de progreso
            progress_stages = {
                'PENDING': {'stage': 'created', 'progress': 10, 'description': 'Ticket creado'},
                'ASSIGNED': {'stage': 'assigned', 'progress': 30, 'description': 'Asignado a técnico'},
                'IN_PROGRESS': {'stage': 'working', 'progress': 60, 'description': 'En proceso de resolución'},
                'RESOLVED_SUCCESS': {'stage': 'resolved', 'progress': 90, 'description': 'Resuelto exitosamente'},
                'RESOLVED_FAILED': {'stage': 'resolved', 'progress': 85, 'description': 'Atendido pero no resuelto'},
                'CLOSED': {'stage': 'closed', 'progress': 100, 'description': 'Cerrado'},
                'CANCELED': {'stage': 'canceled', 'progress': 0, 'description': 'Cancelado'}
            }
            
            current_progress = progress_stages.get(self.status, {'stage': 'unknown', 'progress': 0, 'description': 'Estado desconocido'})
            
            data.update({
                'metrics': {
                    # Métricas de tiempo
                    'total_elapsed_hours': round(total_elapsed_hours, 2),
                    'resolution_time_hours': self.resolution_time_hours,
                    'time_invested_hours': self.time_invested_hours,
                    'business_hours_elapsed': self.business_hours_elapsed,
                    
                    # SLA (Service Level Agreement)
                    'sla': {
                        'target_hours': sla_target_hours,
                        'elapsed_hours': round(total_elapsed_hours, 2),
                        'percentage': round(sla_percentage, 1),
                        'status': sla_status,
                        'remaining_hours': max(0, sla_target_hours - total_elapsed_hours) if sla_status == 'on_time' else 0
                    },
                    
                    # Progreso del ticket
                    'progress': {
                        'current_stage': current_progress['stage'],
                        'percentage': current_progress['progress'],
                        'description': current_progress['description'],
                        'is_open': self.is_open,
                        'is_resolved': self.is_resolved,
                        'can_be_rated': self.can_be_rated
                    },
                    
                    # Métricas de calidad
                    'quality': {
                        'has_rating': self.rating is not None,
                        'rating_value': self.rating,
                        'rating_category': self._get_rating_category(self.rating) if self.rating else None,
                        'has_comments': self.comments.count() > 0 if hasattr(self, 'comments') else False,
                        'resolution_quality': self._get_resolution_quality()
                    }
                }
            })
        
        return data
    
    def _get_rating_category(self, rating):
        """Convierte rating numérico a categoría descriptiva"""
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
        """Determina la calidad de resolución basada en el estado y tiempo"""
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