from . import db

class User(db.Model):
    __tablename__ = "core_users"

    id = db.Column(db.BigInteger, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("core_roles.id", onupdate="CASCADE", ondelete="RESTRICT"), nullable=True)

    username = db.Column(db.Text, unique=True)  # nullable for students
    control_number = db.Column(db.CHAR(8), unique=True)  # nullable for staff
    nip_hash = db.Column(db.Text)
    full_name = db.Column(db.Text, nullable=False)
    email = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, server_default=db.text("TRUE"))
    must_change_password = db.Column(db.Boolean, nullable=False, server_default=db.text("FALSE"))

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.text("NOW()"))

    role = db.relationship("Role", back_populates="users")
    coordinator = db.relationship("Coordinator", back_populates="user", uselist=False, cascade="all, delete", passive_deletes=True)

    # one-to-many
    requests = db.relationship("Request", back_populates="student", cascade="all, delete", passive_deletes=True)
    appointments = db.relationship("Appointment", back_populates="student", cascade="all, delete", passive_deletes=True)
    notifications = db.relationship("Notification", back_populates="user", cascade="all, delete", passive_deletes=True)
    audit_logs = db.relationship("AuditLog", back_populates="actor", cascade="all, delete-orphan", passive_deletes=True)

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
            "full_name": self.full_name,
            "email": self.email,
            "is_active": self.is_active,
            "must_change_password": self.must_change_password,
            "role": {
                "id": self.role.id,
                "name": self.role.name
            } if self.role else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
