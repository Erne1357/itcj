from flask_sqlalchemy import SQLAlchemy

from itcj.core.extensions import db as _db

db = _db
# Import side-effects to register models with SQLAlchemy metadata

from .availability_window import AvailabilityWindow
from .time_slot import TimeSlot
from .request import Request
from .appointment import Appointment
from ....core.models.notification import Notification
from .audit_log import AuditLog

__all__ = [
    "db",
    "Role", "User", "Program", "Coordinator", "ProgramCoordinator",
    "AvailabilityWindow", "TimeSlot", "Request", "Appointment",
    "Notification", "AuditLog",
]
