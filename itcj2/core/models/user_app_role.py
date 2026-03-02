from sqlalchemy import Column, Integer, ForeignKey, Index

from itcj2.models.base import Base


class UserAppRole(Base):
    __tablename__ = "core_user_app_roles"

    user_id = Column(Integer, ForeignKey("core_users.id", ondelete="CASCADE"), primary_key=True)
    app_id  = Column(Integer, ForeignKey("core_apps.id",  ondelete="CASCADE"), primary_key=True)
    role_id = Column(Integer, ForeignKey("core_roles.id", ondelete="CASCADE"), primary_key=True)

    __table_args__ = (
        Index("ix_user_app_roles_user_app", "user_id", "app_id"),
    )
