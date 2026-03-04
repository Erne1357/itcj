from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from itcj2.models.base import Base


class Theme(Base):
    """Temáticas visuales del sistema."""
    __tablename__ = "core_themes"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)

    start_day = Column(Integer, nullable=True)
    start_month = Column(Integer, nullable=True)
    end_day = Column(Integer, nullable=True)
    end_month = Column(Integer, nullable=True)

    is_manually_active = Column(Boolean, nullable=False, default=False)
    is_enabled = Column(Boolean, nullable=False, default=True)
    priority = Column(Integer, nullable=False, default=100)

    colors = Column(JSONB, nullable=False, default=dict)
    custom_css = Column(Text, nullable=False, default="")
    decorations = Column(JSONB, nullable=False, default=dict)

    css_file = Column(String(255), nullable=True)
    js_file = Column(String(255), nullable=True)
    preview_image = Column(String(255), nullable=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    created_by_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="SET NULL"), nullable=True)

    created_by = relationship("User", backref="created_themes", foreign_keys=[created_by_id])

    def is_date_active(self):
        if not all([self.start_day, self.start_month, self.end_day, self.end_month]):
            return False
        today = datetime.now()
        start = (self.start_month, self.start_day)
        end = (self.end_month, self.end_day)
        current = (today.month, today.day)
        if start > end:
            return current >= start or current <= end
        return start <= current <= end

    def is_active(self):
        if not self.is_enabled:
            return False
        return self.is_manually_active or self.is_date_active()

    def get_date_range_display(self):
        if not all([self.start_day, self.start_month, self.end_day, self.end_month]):
            return None
        months = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun",
                  "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
        return f"{self.start_day} {months[self.start_month]} - {self.end_day} {months[self.end_month]}"

    def to_dict(self, include_full=False):
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "start_day": self.start_day,
            "start_month": self.start_month,
            "end_day": self.end_day,
            "end_month": self.end_month,
            "date_range_display": self.get_date_range_display(),
            "is_manually_active": self.is_manually_active,
            "is_enabled": self.is_enabled,
            "is_active": self.is_active(),
            "is_date_active": self.is_date_active(),
            "priority": self.priority,
            "preview_image": self.preview_image,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_full:
            data.update({
                "colors": self.colors or {},
                "custom_css": self.custom_css or "",
                "decorations": self.decorations or {},
                "css_file": self.css_file,
                "js_file": self.js_file,
            })
        return data

    def __repr__(self):
        status = "active" if self.is_active() else "inactive"
        return f"<Theme {self.id} '{self.name}' ({status})>"
