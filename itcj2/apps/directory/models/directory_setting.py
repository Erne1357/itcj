"""Ajustes de la app Directory. Tabla singleton: exactamente una fila, id = 1.

La fila 1 la siembra la MIGRACIÓN, no el DML (el DML solo carga permisos y en CI
ni siquiera corre). Los lectores deben tolerar que la fila no exista: CI construye
el esquema con Base.metadata.create_all, sin Alembic ni DML.
"""
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer,
)
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class DirectorySettings(Base):
    __tablename__ = "directory_settings"

    id = Column(Integer, primary_key=True, autoincrement=False)
    show_unofficial_departments = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    updated_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_directory_settings_singleton"),
    )

    def __repr__(self):
        return f"<DirectorySettings show_unofficial={self.show_unofficial_departments}>"
