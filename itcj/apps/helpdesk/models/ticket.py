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
    office_document_folio = db.Column(db.String(50), nullable=True)  # Folio de oficio (opcional)
    
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
        return calculate_business_hours(self.created_at, self.resolved_at)

    def to_dict(self, include_relations=False):
        data = {
            'id': self.id,
            'ticket_number': self.ticket_number,
            'title': self.title,
            'description': self.description,
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
        }
        
        if include_relations:
            data.update({
                'requester': {
                    'id': self.requester.id,
                    'name': self.requester.name,
                    'username': self.requester.username
                } if self.requester else None,
                'category': self.category.to_dict() if self.category else None,
                'assigned_to': {
                    'id': self.assigned_to.id,
                    'name': self.assigned_to.name,
                    'username': self.assigned_to.username
                } if self.assigned_to else None,
                'assigned_to_team': self.assigned_to_team,
                'department': {
                    'id': self.requester_department.id,
                    'name': self.requester_department.name
                } if self.requester_department else None,
            })
        
        return data