from sqlalchemy import Column, Integer, String, Text, ForeignKey, UniqueConstraint

from itcj2.models.base import Base


class Permission(Base):
    __tablename__ = "core_permissions"

    id = Column(Integer, primary_key=True)
    app_id = Column(Integer, ForeignKey("core_apps.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(100), nullable=False)
    name = Column(String(120), nullable=False)
    description = Column(Text)

    __table_args__ = (
        UniqueConstraint("app_id", "code", name="uq_permissions_app_code"),
    )
