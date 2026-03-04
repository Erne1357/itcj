from sqlalchemy import Column, Integer, Text
from sqlalchemy.orm import relationship

from itcj2.models.base import Base


class Role(Base):
    __tablename__ = "core_roles"

    id = Column(Integer, primary_key=True)
    name = Column(Text, unique=True, nullable=False)

    users = relationship("User", back_populates="role", cascade="all, delete", passive_deletes=True)

    def __repr__(self) -> str:
        return f"<Role {self.name}>"
