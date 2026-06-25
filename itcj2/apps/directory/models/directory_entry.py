"""Extensiones telefónicas que NO vienen de un puesto (recepción, conmutador, etc.)."""
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from itcj2.models.base import Base


class DirectoryEntry(Base):
    """Extensión extra del directorio, colgada de un departamento."""
    __tablename__ = "directory_entries"

    id = Column(Integer, primary_key=True)
    department_id = Column(Integer, ForeignKey("core_departments.id"), nullable=False, index=True)
    position_id = Column(Integer, ForeignKey("core_positions.id"), nullable=True, index=True)
    label = Column(String(120), nullable=False)
    holder_name = Column(String(120), nullable=True)
    extension = Column(String(10), nullable=False, index=True)
    notes = Column(String(200), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)

    department = relationship("Department")
    position = relationship("Position")

    def __repr__(self):
        return f"<DirectoryEntry {self.extension}: {self.label}>"
