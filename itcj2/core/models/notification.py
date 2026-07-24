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
    user_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="CASCADE"), nullable=False, index=True)
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

    def to_dict(self, include_source=False, styles: dict | None = None):
        sanitized_data = {}
        if self.data:
            for key, value in self.data.items():
                sanitized_data[key] = list(value) if isinstance(value, (set, frozenset)) else value

        style = self._resolve_style(styles)
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
            "app_icon": self._get_app_icon(style),
            "app_color": self._get_app_color(),
            "app_color_hex": style.get("color"),
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

    # Mapas legacy: fallback cuando la app no está en core_apps o no tiene estilo.
    _LEGACY_ICONS = {
        "agendatec": "bi-calendar-check",
        "helpdesk": "bi-headset",
        "maint": "bi-tools",
        "vistetec": "bi-bag-heart",
        "titulatec": "bi-mortarboard-fill",
        "warehouse": "bi-archive",
        "inventory": "bi-box-seam",
        "core": "bi-gear",
    }
    _LEGACY_COLORS = {
        "agendatec": "primary",
        "helpdesk": "success",
        "maint": "secondary",
        "vistetec": "danger",
        "titulatec": "warning",
        "warehouse": "info",
        "inventory": "warning",
        "core": "secondary",
    }

    def _resolve_style(self, styles: dict | None) -> dict:
        """Estilo de ESTA app. ``styles`` = mapa {app_key: {...}} de
        ``cached_app_styles`` que los hot paths de lista pasan UNA vez al
        serializar N notificaciones (evita 1 GET Redis — o 1 scan de core_apps
        con Redis caído — POR notificación). Si es None, resuelve por-fila
        (paths de 1 notificación)."""
        if styles is not None:
            return styles.get(self.app_name) or {}
        return self._app_style()

    def _app_style(self) -> dict:
        """Estilo (color/icon_class) desde core_apps vía app_style_cache.

        Fail-open: sin session ORM o ante cualquier error devuelve {} y los
        helpers caen a los mapas legacy.
        """
        from sqlalchemy.orm import object_session
        db = object_session(self)
        if db is None:
            return {}
        try:
            from itcj2.core.services.app_style_cache import cached_app_styles
            return cached_app_styles(db).get(self.app_name) or {}
        except Exception:
            return {}

    def _get_app_icon(self, style: dict | None = None):
        style = self._app_style() if style is None else style
        if style.get("icon_class"):
            return style["icon_class"]
        return self._LEGACY_ICONS.get(self.app_name, "bi-bell")

    def _get_app_color(self):
        # F1b-D1: tono Bootstrap legacy — los widgets renderizan `bg-${app_color}`
        # como CLASE. El hex de BD viaja en app_color_hex; el flip de los widgets
        # a hex es de F6 (mismo commit que sus consumidores). NO devolver hex aquí.
        return self._LEGACY_COLORS.get(self.app_name, "info")
