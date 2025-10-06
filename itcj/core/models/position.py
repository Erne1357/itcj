# itcj/core/models/position.py
from itcj.core.extensions import db
from datetime import datetime

class Position(db.Model):
    """Puestos organizacionales (Coordinador, Jefe de Depto, etc.)"""
    __tablename__ = "positions"
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)  # ej: 'coord_sistemas'
    title = db.Column(db.String(120), nullable=False)  # ej: 'Coordinador de Sistemas'
    description = db.Column(db.Text)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now(), nullable=False)
    allows_multiple = db.Column(db.Boolean, nullable=False, default=False)  # Si varios usuarios pueden tener este puesto simultáneamente
    # Relaciones
    user_assignments = db.relationship("UserPosition", back_populates="position", cascade="all, delete-orphan")
    app_role_assignments = db.relationship("PositionAppRole", back_populates="position", cascade="all, delete-orphan")
    app_perm_assignments = db.relationship("PositionAppPerm", back_populates="position", cascade="all, delete-orphan")
    department = db.relationship('Department', back_populates='positions')

    def __repr__(self):
        return f"<Position {self.code}: {self.title}>"

class UserPosition(db.Model):
    """Asignación de usuarios a puestos (con fechas de vigencia)"""
    __tablename__ = "user_positions"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    position_id = db.Column(db.Integer, db.ForeignKey("positions.id", ondelete="CASCADE"), nullable=False, index=True)
    start_date = db.Column(db.Date, nullable=False, default=db.func.current_date())
    end_date = db.Column(db.Date)  # NULL significa activo
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    notes = db.Column(db.Text)  # Notas sobre la asignación
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    
    # Relaciones
    user = db.relationship("User", backref="position_assignments")
    position = db.relationship("Position", back_populates="user_assignments")
    
    __table_args__ = (
        db.Index("ix_user_positions_active", "user_id", "position_id", "is_active"),
        # Un usuario solo puede tener un puesto activo del mismo tipo a la vez
        db.UniqueConstraint("user_id", "position_id", "is_active", name="uq_active_user_position"),
    )

class PositionAppRole(db.Model):
    """Roles que tiene un puesto en cada aplicación"""
    __tablename__ = "position_app_roles"
    
    position_id = db.Column(db.Integer, db.ForeignKey("positions.id", ondelete="CASCADE"), primary_key=True)
    app_id = db.Column(db.Integer, db.ForeignKey("apps.id", ondelete="CASCADE"), primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    
    # Relaciones
    position = db.relationship("Position", back_populates="app_role_assignments")
    app = db.relationship("App")
    role = db.relationship("Role")
    
    __table_args__ = (
        db.Index("ix_position_app_roles_position_app", "position_id", "app_id"),
    )

class PositionAppPerm(db.Model):
    """Permisos directos que tiene un puesto en cada aplicación"""
    __tablename__ = "position_app_perms"
    
    position_id = db.Column(db.Integer, db.ForeignKey("positions.id", ondelete="CASCADE"), primary_key=True)
    app_id = db.Column(db.Integer, db.ForeignKey("apps.id", ondelete="CASCADE"), primary_key=True)
    perm_id = db.Column(db.Integer, db.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)
    allow = db.Column(db.Boolean, nullable=False, default=True)
    
    # Relaciones
    position = db.relationship("Position", back_populates="app_perm_assignments")
    app = db.relationship("App")
    permission = db.relationship("Permission")
    
    __table_args__ = (
        db.Index("ix_position_app_perms_position_app", "position_id", "app_id"),
    )

# itcj/core/models/program_position.py (específico para AgendaTec)
class ProgramPosition(db.Model):
    """Relación entre puestos y programas académicos (ej: coordinadores)"""
    __tablename__ = "program_positions"
    
    id = db.Column(db.Integer, primary_key=True)
    position_id = db.Column(db.Integer, db.ForeignKey("positions.id", ondelete="CASCADE"), nullable=False)
    program_id = db.Column(db.Integer, db.ForeignKey("programs.id", ondelete="CASCADE"), nullable=False)
    responsibilities = db.Column(db.Text)  # Responsabilidades específicas
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    
    # Relaciones
    position = db.relationship("Position")
    program = db.relationship("Program")
    
    __table_args__ = (
        db.UniqueConstraint("position_id", "program_id", name="uq_position_program"),
        db.Index("ix_program_positions_position", "position_id"),
        db.Index("ix_program_positions_program", "program_id"),
    )