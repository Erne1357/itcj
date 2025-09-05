from flask_sqlalchemy import SQLAlchemy

from ....extensions import db as _db

db = _db
# Import side-effects to register models with SQLAlchemy metadata
from .role import Role
from .user import User
from .program import Program
from .coordinator import Coordinator
from .program_coordinator import ProgramCoordinator
from .availability_window import AvailabilityWindow
from .time_slot import TimeSlot
from .request import Request
from .appointment import Appointment
from .notification import Notification
from .audit_log import AuditLog

__all__ = [
    "db",
    "Role", "User", "Program", "Coordinator", "ProgramCoordinator",
    "AvailabilityWindow", "TimeSlot", "Request", "Appointment",
    "Notification", "AuditLog",
]
