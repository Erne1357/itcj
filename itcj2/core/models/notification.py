from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, ENUM
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from itcj2.models.base import Base

notif_type_pg_enum = ENUM(
    "APPOINTMENT_CREATED", "APPOINTMENT_CANCELED",
    "REQUEST_STATUS_CHANGED", "DROP_CREATED", "SYSTEM",
    name="notif_type_enum", create_type=False,
)


class Notification(Base):
    __tablename__ = "core_notifications"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False, index=True)
    app_name = Column(String(50), nullable=False, index=True)
    type = Column(String(100), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    body = Column(Text)
    data = Column(JSONB, nullable=False, default=dict)
    is_read = Column(Boolean, nullable=False, default=False, index=True)
    read_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    # AgendaTec
    source_request_id = Column(BigInteger, ForeignKey("agendatec_requests.id", ondelete="SET NULL"))
    source_appointment_id = Column(BigInteger, ForeignKey("agendatec_appointments.id", ondelete="SET NULL"))
    program_id = Column(Integer, ForeignKey("core_programs.id", ondelete="SET NULL"))

    # Helpdesk
    ticket_id = Column(Integer, ForeignKey("helpdesk_ticket.id", ondelete="CASCADE"))

    user = relationship("User", back_populates="notifications")
    ticket = relationship("Ticket", backref="notifications")

    __table_args__ = (
        Index("ix_notifications_user_app", "user_id", "app_name"),
        Index("ix_notifications_user_unread", "user_id", "is_read"),
        Index("ix_notifications_app_type", "app_name", "type"),
    )

    def to_dict(self, include_source=False):
        sanitized_data = {}
        if self.data:
            for key, value in self.data.items():
                sanitized_data[key] = list(value) if isinstance(value, (set, frozenset)) else value

        data = {
            "id": self.id,
            "app_name": self.app_name,
            "type": self.type,
            "title": self.title,
            "body": self.body,
            "data": sanitized_data,
            "is_read": self.is_read,
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "action_url": self._get_action_url(),
            "app_icon": self._get_app_icon(),
            "app_color": self._get_app_color(),
        }
        if include_source and self.ticket:
            data["ticket"] = {
                "id": self.ticket.id,
                "ticket_number": self.ticket.ticket_number,
                "title": self.ticket.title,
            }
        return data

    def _get_action_url(self):
        return self.data.get("url") if self.data else None

    def _get_app_icon(self):
        icons = {
            "agendatec": "bi-calendar-check",
            "helpdesk": "bi-headset",
            "inventory": "bi-box-seam",
            "core": "bi-gear",
        }
        return icons.get(self.app_name, "bi-bell")

    def _get_app_color(self):
        colors = {
            "agendatec": "primary",
            "helpdesk": "success",
            "inventory": "warning",
            "core": "secondary",
        }
        return colors.get(self.app_name, "info")
