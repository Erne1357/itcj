from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy import func, case
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship, object_session
from sqlalchemy.sql import text

from itcj2.models.base import Base


class User(Base):
    __tablename__ = "core_users"

    id = Column(BigInteger, primary_key=True)
    role_id = Column(
        Integer,
        ForeignKey("core_roles.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=True,
    )
    username = Column(Text, unique=True)
    control_number = Column(Text, unique=True)
    password_hash = Column(Text)

    first_name = Column(Text, nullable=False)
    last_name = Column(Text, nullable=False)
    middle_name = Column(Text, nullable=True)

    email = Column(Text)
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"))
    must_change_password = Column(Boolean, nullable=False, server_default=text("FALSE"))
    last_login = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    role = relationship("Role", back_populates="users")
    coordinator = relationship(
        "Coordinator", back_populates="user",
        uselist=False, cascade="all, delete", passive_deletes=True,
    )
    requests = relationship(
        "Request", back_populates="student",
        cascade="all, delete", passive_deletes=True,
    )
    appointments = relationship(
        "Appointment",
        back_populates="student", cascade="all, delete", passive_deletes=True,
    )
    notifications = relationship(
        "Notification", back_populates="user",
        cascade="all, delete", passive_deletes=True,
    )
    audit_logs = relationship(
        "AuditLog", back_populates="actor",
        cascade="all, delete-orphan", passive_deletes=True,
    )

    # Help-Desk
    tickets_created = relationship(
        "Ticket", foreign_keys="Ticket.created_by_id",
        back_populates="created_by_user", cascade="all, delete", passive_deletes=True,
    )
    tickets_updated = relationship(
        "Ticket", foreign_keys="Ticket.updated_by_id",
        back_populates="updated_by_user", cascade="all, delete", passive_deletes=True,
    )
    tickets_requested = relationship(
        "Ticket", foreign_keys="Ticket.requester_id",
        back_populates="requester", cascade="all, delete", passive_deletes=True,
    )
    tickets_assigned = relationship(
        "Ticket", foreign_keys="Ticket.assigned_to_user_id",
        back_populates="assigned_to", cascade="all, delete", passive_deletes=True,
    )
    tickets_resolved = relationship(
        "Ticket", foreign_keys="Ticket.resolved_by_id",
        back_populates="resolved_by", cascade="all, delete", passive_deletes=True,
    )

    @hybrid_property
    def full_name(self):
        if self.middle_name:
            return f"{self.last_name} {self.middle_name} {self.first_name}"
        return f"{self.last_name} {self.first_name}"

    @full_name.expression
    def full_name(cls):
        return case(
            (cls.middle_name.isnot(None),
             func.concat(cls.last_name, " ", cls.middle_name, " ", cls.first_name)),
            else_=func.concat(cls.last_name, " ", cls.first_name),
        )

    def __repr__(self) -> str:
        return f"<User {self.id} {self.full_name}>"

    def get_current_position(self):
        """Obtiene el puesto activo actual del usuario."""
        from itcj2.core.models.position import UserPosition
        db = object_session(self)
        return db.query(UserPosition).filter_by(user_id=self.id, is_active=True).first()

    def get_current_department(self):
        pos = self.get_current_position()
        return pos.position.department if pos and pos.position else None

    def get_position_email(self):
        pos = self.get_current_position()
        return pos.position.email if pos and pos.position else None

    def get_position_title(self):
        pos = self.get_current_position()
        return pos.position.title if pos and pos.position else None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "control_number": self.control_number,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "middle_name": self.middle_name,
            "full_name": self.full_name,
            "email": self.email,
            "is_active": self.is_active,
            "must_change_password": self.must_change_password,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "role": {"id": self.role.id, "name": self.role.name} if self.role else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
