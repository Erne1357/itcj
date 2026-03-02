from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, ForeignKey,
    Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from itcj2.models.base import Base


class Position(Base):
    """Puestos organizacionales (Coordinador, Jefe de Depto, etc.)"""
    __tablename__ = "core_positions"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(String(120), nullable=False)
    description = Column(Text)
    email = Column(String(150), nullable=True, unique=True, index=True)
    department_id = Column(Integer, ForeignKey("core_departments.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    allows_multiple = Column(Boolean, nullable=False, default=False)
    phone_extension = Column(String(10), nullable=True)
    phone_notes = Column(String(200), nullable=True)

    user_assignments = relationship("UserPosition", back_populates="position", cascade="all, delete-orphan")
    app_role_assignments = relationship("PositionAppRole", back_populates="position", cascade="all, delete-orphan")
    app_perm_assignments = relationship("PositionAppPerm", back_populates="position", cascade="all, delete-orphan")
    department = relationship("Department", back_populates="positions")

    def __repr__(self):
        return f"<Position {self.code}: {self.title}>"


class UserPosition(Base):
    """Asignación de usuarios a puestos (con fechas de vigencia)"""
    __tablename__ = "core_user_positions"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="CASCADE"), nullable=False, index=True)
    position_id = Column(Integer, ForeignKey("core_positions.id", ondelete="CASCADE"), nullable=False, index=True)
    start_date = Column(Date, nullable=False, default=func.current_date())
    end_date = Column(Date)
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    user = relationship("User", backref="position_assignments")
    position = relationship("Position", back_populates="user_assignments")

    __table_args__ = (
        Index("ix_user_positions_active", "user_id", "position_id", "is_active"),
        UniqueConstraint("user_id", "position_id", "is_active", name="uq_active_user_position"),
    )


class PositionAppRole(Base):
    """Roles que tiene un puesto en cada aplicación"""
    __tablename__ = "core_position_app_roles"

    position_id = Column(Integer, ForeignKey("core_positions.id", ondelete="CASCADE"), primary_key=True)
    app_id = Column(Integer, ForeignKey("core_apps.id", ondelete="CASCADE"), primary_key=True)
    role_id = Column(Integer, ForeignKey("core_roles.id", ondelete="CASCADE"), primary_key=True)

    position = relationship("Position", back_populates="app_role_assignments")
    app = relationship("App")
    role = relationship("Role")

    __table_args__ = (
        Index("ix_position_app_roles_position_app", "position_id", "app_id"),
    )


class PositionAppPerm(Base):
    """Permisos directos que tiene un puesto en cada aplicación"""
    __tablename__ = "core_position_app_perms"

    position_id = Column(Integer, ForeignKey("core_positions.id", ondelete="CASCADE"), primary_key=True)
    app_id = Column(Integer, ForeignKey("core_apps.id", ondelete="CASCADE"), primary_key=True)
    perm_id = Column(Integer, ForeignKey("core_permissions.id", ondelete="CASCADE"), primary_key=True)
    allow = Column(Boolean, nullable=False, default=True)

    position = relationship("Position", back_populates="app_perm_assignments")
    app = relationship("App")
    permission = relationship("Permission")

    __table_args__ = (
        Index("ix_position_app_perms_position_app", "position_id", "app_id"),
    )


class ProgramPosition(Base):
    """Relación entre puestos y programas académicos"""
    __tablename__ = "core_program_positions"

    id = Column(Integer, primary_key=True)
    position_id = Column(Integer, ForeignKey("core_positions.id", ondelete="CASCADE"), nullable=False)
    program_id = Column(Integer, ForeignKey("core_programs.id", ondelete="CASCADE"), nullable=False)
    responsibilities = Column(Text)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    position = relationship("Position")
    program = relationship("Program")

    __table_args__ = (
        UniqueConstraint("position_id", "program_id", name="uq_position_program"),
        Index("ix_program_positions_position", "position_id"),
        Index("ix_program_positions_program", "program_id"),
    )
