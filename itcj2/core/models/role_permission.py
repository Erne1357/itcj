from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import relationship

from itcj2.models.base import Base


class RolePermission(Base):
    __tablename__ = "core_role_permissions"

    role_id = Column(Integer, ForeignKey("core_roles.id", ondelete="CASCADE"), primary_key=True)
    perm_id = Column(Integer, ForeignKey("core_permissions.id", ondelete="CASCADE"), primary_key=True)

    permission = relationship("Permission", lazy="joined")
