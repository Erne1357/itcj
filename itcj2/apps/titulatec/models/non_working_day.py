"""Días inhábiles del calendario de TitulaTec (fase 5).

Con la tabla vacía todo conteo de días hábiles da exactamente lo de antes
(lunes a viernes). Spec 2026-10-22-titulatec-fase5-revision-sinodales §5.
"""
from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import text

from itcj2.models.base import Base


class NonWorkingDay(Base):
    __tablename__ = "titulatec_non_working_days"

    id = Column(Integer, primary_key=True)
    day = Column(Date, nullable=False, unique=True)
    description = Column(String(150), nullable=False)
    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    def __repr__(self) -> str:
        return f"<NonWorkingDay {self.day}>"
