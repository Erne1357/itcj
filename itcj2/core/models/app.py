from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from itcj2.models.base import Base


class App(Base):
    __tablename__ = "core_apps"

    id = Column(Integer, primary_key=True)
    key = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Campos mobile
    visible_to_students = Column(Boolean, nullable=False, default=False)
    mobile_icon = Column(String(100), nullable=True)
    mobile_url = Column(String(255), nullable=True)
    mobile_enabled = Column(Boolean, nullable=False, default=True)

    permissions = relationship("Permission", backref="app", cascade="all, delete-orphan", lazy="dynamic")

    def to_dict(self, include_mobile=False):
        data = {
            "id": self.id,
            "key": self.key,
            "name": self.name,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_mobile:
            data.update({
                "visible_to_students": self.visible_to_students,
                "mobile_icon": self.mobile_icon,
                "mobile_url": self.mobile_url,
                "mobile_enabled": self.mobile_enabled,
            })
        return data
