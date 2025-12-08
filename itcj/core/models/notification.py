# models/notification.py
from sqlalchemy.dialects.postgresql import JSONB, ENUM
from ...apps.agendatec.models import db

notif_type_pg_enum = ENUM("APPOINTMENT_CREATED","APPOINTMENT_CANCELED", "REQUEST_STATUS_CHANGED", "DROP_CREATED", "SYSTEM",name="notif_type_enum", create_type=False)

class Notification(db.Model):
    __tablename__ = "core_notifications"
    
    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("core_users.id"), nullable=False, index=True)
    app_name = db.Column(db.String(50), nullable=False, index=True)
    # Valores: 'agendatec', 'helpdesk', 'inventory', etc.
    
    type = db.Column(db.String(100), nullable=False, index=True)
    # Ejemplos:
    # AgendaTec: APPOINTMENT_CREATED, REQUEST_STATUS_CHANGED
    # Helpdesk: TICKET_CREATED, TICKET_ASSIGNED, TICKET_RESOLVED
    
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text)
    data = db.Column(JSONB, nullable=False, default=dict)    
    is_read = db.Column(db.Boolean, nullable=False, default=False, index=True)
    read_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), index=True)
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), server_onupdate=db.func.now())
    
    # AgendaTec
    source_request_id = db.Column(db.BigInteger, db.ForeignKey("agendatec_requests.id", ondelete="SET NULL"))
    source_appointment_id = db.Column(db.BigInteger, db.ForeignKey("agendatec_appointments.id", ondelete="SET NULL"))
    program_id = db.Column(db.Integer, db.ForeignKey("core_programs.id", ondelete="SET NULL"))
    
    # Helpdesk
    ticket_id = db.Column(db.Integer, db.ForeignKey("helpdesk_ticket.id", ondelete="CASCADE"))
    
    # Relaciones
    user = db.relationship("User", back_populates="notifications")
    ticket = db.relationship("Ticket", backref="notifications")
    
    # Índices compuestos
    __table_args__ = (
        db.Index('ix_notifications_user_app', 'user_id', 'app_name'),
        db.Index('ix_notifications_user_unread', 'user_id', 'is_read'),
        db.Index('ix_notifications_app_type', 'app_name', 'type'),
    )
    
    def to_dict(self, include_source=False):
        # Sanitizar el campo data para asegurar que sea JSON serializable
        sanitized_data = {}
        if self.data:
            for key, value in self.data.items():
                # Convertir sets a listas
                if isinstance(value, (set, frozenset)):
                    sanitized_data[key] = list(value)
                else:
                    sanitized_data[key] = value
        
        data = {
            'id': self.id,
            'app_name': self.app_name,
            'type': self.type,
            'title': self.title,
            'body': self.body,
            'data': sanitized_data,
            'is_read': self.is_read,
            'read_at': self.read_at.isoformat() if self.read_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'action_url': self._get_action_url(),
            'app_icon': self._get_app_icon(),
            'app_color': self._get_app_color(),
        }

        if include_source and self.ticket:
            data['ticket'] = {
                'id': self.ticket.id,
                'ticket_number': self.ticket.ticket_number,
                'title': self.ticket.title
            }

        return data

    def _get_action_url(self):
        """Extrae la URL de acción desde el campo data JSONB"""
        if not self.data:
            return None
        return self.data.get('url')

    def _get_app_icon(self):
        """Retorna el icono correspondiente a cada aplicación"""
        icons = {
            'agendatec': 'bi-calendar-check',
            'helpdesk': 'bi-headset',
            'inventory': 'bi-box-seam',
            'core': 'bi-gear',
        }
        return icons.get(self.app_name, 'bi-bell')

    def _get_app_color(self):
        """Retorna el color correspondiente a cada aplicación"""
        colors = {
            'agendatec': 'primary',
            'helpdesk': 'success',
            'inventory': 'warning',
            'core': 'secondary',
        }
        return colors.get(self.app_name, 'info')