from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship, object_session
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class Department(Base):
    __tablename__ = "core_departments"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    icon_class = Column(String(50), nullable=True)
    parent_id = Column(Integer, ForeignKey("core_departments.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=func.now(), server_default=text("NOW()"), nullable=False)

    positions = relationship("Position", back_populates="department", lazy="dynamic")
    parent = relationship("Department", remote_side=[id], backref="subdepartments")

    def is_direction(self):
        return self.parent_id is None

    def is_subdirection(self):
        if self.parent_id is None:
            return False
        db = object_session(self)
        parent = db.get(Department, self.parent_id)
        return parent and parent.parent_id is None

    def get_children_count(self):
        db = object_session(self)
        return db.query(Department).filter_by(parent_id=self.id, is_active=True).count()

    def get_head_position(self):
        return self.positions.filter_by(
            code=f"head_{self.code}",
            is_active=True,
        ).first()

    def get_head_user(self):
        head_position = self.get_head_position()
        if not head_position:
            return None
        from itcj2.core.models.position import UserPosition
        db = object_session(self)
        assignment = db.query(UserPosition).filter_by(
            position_id=head_position.id, is_active=True
        ).first()
        return assignment.user if assignment else None

    def to_dict(self, include_children=False):
        head_user = self.get_head_user()
        db = object_session(self)
        data = {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "icon_class": self.icon_class or "bi-building",
            "is_active": self.is_active,
            "is_subdirection": self.is_subdirection(),
            "parent_id": self.parent_id,
            "positions_count": self.positions.filter_by(is_active=True).count(),
            "children_count": self.get_children_count(),
            "head": {"full_name": head_user.full_name, "email": head_user.email}
            if head_user
            else None,
        }
        if include_children and (self.is_direction() or self.is_subdirection()):
            data["children"] = [
                child.to_dict()
                for child in db.query(Department).filter_by(
                    parent_id=self.id, is_active=True
                ).all()
            ]
        return data
