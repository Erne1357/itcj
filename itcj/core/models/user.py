from . import db
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import func, case

class User(db.Model):
    __tablename__ = "core_users"

    id = db.Column(db.BigInteger, primary_key=True)

    username = db.Column(db.Text, unique=True)  # nullable for students
    control_number = db.Column(db.CHAR(8), unique=True)  # nullable for staff
    password_hash = db.Column(db.Text)

    # Nombre dividido en partes (nuevo estándar)
    first_name = db.Column(db.Text, nullable=False)  # Nombre(s) - OBLIGATORIO
    last_name = db.Column(db.Text, nullable=False)   # Apellido paterno - OBLIGATORIO
    middle_name = db.Column(db.Text, nullable=True)  # Apellido materno - OPCIONAL

    email = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, server_default=db.text("TRUE"))
    must_change_password = db.Column(db.Boolean, nullable=False, server_default=db.text("FALSE"))

    # Role (deprecated - usar sistema de roles por app, pero mantener por compatibilidad)
    role_id = db.Column(db.Integer, db.ForeignKey("core_roles.id", onupdate="CASCADE", ondelete="SET NULL"), nullable=True)

    # Audit fields
    created_by_id = db.Column(db.BigInteger, db.ForeignKey("core_users.id", onupdate="CASCADE", ondelete="SET NULL"), nullable=True, server_default=db.text("10"))
    updated_by_id = db.Column(db.BigInteger, db.ForeignKey("core_users.id", onupdate="CASCADE", ondelete="SET NULL"), nullable=True, server_default=db.text("10"))

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))

    # Relationships
    role = db.relationship("Role", back_populates="users")
    created_by = db.relationship("User", foreign_keys=[created_by_id], remote_side=[id], uselist=False)
    updated_by = db.relationship("User", foreign_keys=[updated_by_id], remote_side=[id], uselist=False)
    coordinator = db.relationship("Coordinator", back_populates="user", uselist=False, cascade="all, delete", passive_deletes=True)

    # one-to-many
    requests = db.relationship("Request", back_populates="student", cascade="all, delete", passive_deletes=True)
    appointments = db.relationship("Appointment", back_populates="student", cascade="all, delete", passive_deletes=True)
    notifications = db.relationship("Notification", back_populates="user", cascade="all, delete", passive_deletes=True)
    audit_logs = db.relationship("AuditLog", back_populates="actor", cascade="all, delete-orphan", passive_deletes=True)

    # ==================== Help-Desk ====================
    tickets_created = db.relationship("Ticket", foreign_keys='Ticket.created_by_id', back_populates="created_by_user", cascade="all, delete", passive_deletes=True)
    tickets_updated = db.relationship("Ticket", foreign_keys='Ticket.updated_by_id', back_populates="updated_by_user", cascade="all, delete", passive_deletes=True)
    tickets_requested = db.relationship("Ticket", foreign_keys='Ticket.requester_id', back_populates="requester", cascade="all, delete", passive_deletes=True)
    tickets_assigned = db.relationship("Ticket", foreign_keys='Ticket.assigned_to_user_id', back_populates="assigned_to", cascade="all, delete", passive_deletes=True)
    tickets_resolved = db.relationship("Ticket", foreign_keys='Ticket.resolved_by_id', back_populates="resolved_by", cascade="all, delete", passive_deletes=True)
    
    @hybrid_property
    def full_name(self):
        """Nombre completo calculado a partir de las partes (propiedad Python)"""
        if self.middle_name:
            return f"{self.last_name} {self.middle_name} {self.first_name}"
        return f"{self.last_name} {self.first_name}"
    
    @full_name.expression
    def full_name(cls):
        """Expresión SQL para full_name (para queries y ordenamiento)"""
        return case(
            (cls.middle_name.isnot(None),
             func.concat(cls.last_name, ' ', cls.middle_name, ' ', cls.first_name)),
            else_=func.concat(cls.last_name, ' ', cls.first_name)
        )

    def __repr__(self) -> str:
        return f"<User {self.id} {self.full_name}>"
    
    def get_current_position(self):
        """Obtiene el puesto activo actual del usuario"""
        from itcj.core.models.position import UserPosition
        return UserPosition.query.filter_by(
            user_id=self.id,
            is_active=True
        ).first()
    
    def get_current_department(self):
        """Obtiene el departamento actual del usuario a través de su puesto"""
        position_assignment = self.get_current_position()
        return position_assignment.position.department if position_assignment and position_assignment.position else None
    
    def get_position_email(self):
        """Obtiene el email oficial del puesto actual"""
        position_assignment = self.get_current_position()
        return position_assignment.position.email if position_assignment and position_assignment.position else None
    
    def get_position_title(self):
        """Obtiene el título del puesto actual"""
        position_assignment = self.get_current_position()
        return position_assignment.position.title if position_assignment and position_assignment.position else None
    
    def to_dict(self) -> dict:
        """Serialización para API"""
        return {
            "id": self.id,
            "username": self.username,
            "control_number": self.control_number,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "middle_name": self.middle_name,
            "full_name": self.full_name,  # Propiedad calculada
            "email": self.email,
            "is_active": self.is_active,
            "must_change_password": self.must_change_password,
            "role": self.role.name if self.role else None,  # Puede ser None
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by_id": self.created_by_id,
            "updated_by_id": self.updated_by_id
        }
