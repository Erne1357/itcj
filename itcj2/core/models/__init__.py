"""Modelos core de itcj2 (SQLAlchemy nativo, sin Flask-SQLAlchemy)."""

from .role import Role
from .user import User
from .app import App
from .permission import Permission
from .role_permission import RolePermission
from .user_app_role import UserAppRole
from .user_app_perm import UserAppPerm
from .coordinator import Coordinator
from .program import Program
from .program_coordinator import ProgramCoordinator
from .academic_period import AcademicPeriod
from .theme import Theme
from .department import Department
from .notification import Notification
from .position import Position, UserPosition, PositionAppRole, PositionAppPerm, ProgramPosition
from .task_models import TaskDefinition, PeriodicTask, TaskRun

__all__ = [
    "Role", "User", "App", "Permission", "RolePermission",
    "UserAppRole", "UserAppPerm", "Coordinator", "Program",
    "ProgramCoordinator", "AcademicPeriod", "Theme", "Department",
    "Notification", "Position", "UserPosition", "PositionAppRole",
    "PositionAppPerm", "ProgramPosition",
    "TaskDefinition", "PeriodicTask", "TaskRun",
]
