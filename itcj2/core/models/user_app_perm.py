from sqlalchemy import Column, Integer, Boolean, ForeignKey, Index

from itcj2.models.base import Base


class UserAppPerm(Base):
    __tablename__ = "core_user_app_perms"

    user_id = Column(Integer, ForeignKey("core_users.id", ondelete="CASCADE"), primary_key=True)
    app_id  = Column(Integer, ForeignKey("core_apps.id",  ondelete="CASCADE"), primary_key=True)
    perm_id = Column(Integer, ForeignKey("core_permissions.id", ondelete="CASCADE"), primary_key=True)
    allow   = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_user_app_perms_user_app", "user_id", "app_id"),
    )
