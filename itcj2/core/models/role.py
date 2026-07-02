from sqlalchemy import Column, Integer, Text
from sqlalchemy.orm import relationship

from itcj2.models.base import Base


class Role(Base):
    __tablename__ = "core_roles"

    id = Column(Integer, primary_key=True)
    name = Column(Text, unique=True, nullable=False)

    # NO cascade de borrado: borrar un rol NUNCA debe borrar usuarios. La BD
    # protege con ON DELETE RESTRICT en core_users.role_id.
    users = relationship("User", back_populates="role", cascade="save-update, merge", passive_deletes=True)

    def __repr__(self) -> str:
        return f"<Role {self.name}>"
