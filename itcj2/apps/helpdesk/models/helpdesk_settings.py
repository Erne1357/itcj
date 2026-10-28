"""Ajustes del helpdesk. Tabla singleton: exactamente una fila, id = 1.

La fila 1 la siembra la MIGRACION; los lectores deben tolerar que no exista
(CI arma el esquema con Base.metadata.create_all, sin Alembic ni DML).
"""
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON,
)
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class HelpdeskSettings(Base):
    __tablename__ = "helpdesk_settings"

    id = Column(Integer, primary_key=True, autoincrement=False)
    auto_assign_enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Ids de tecnicos que reciben correo al asignarles un ticket
    assignment_email_user_ids = Column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    updated_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_helpdesk_settings_singleton"),
    )

    def __repr__(self):
        return f"<HelpdeskSettings auto_assign={self.auto_assign_enabled}>"
