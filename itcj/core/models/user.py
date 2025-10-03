from . import db

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.BigInteger, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id", onupdate="CASCADE", ondelete="RESTRICT"), nullable=False)

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
