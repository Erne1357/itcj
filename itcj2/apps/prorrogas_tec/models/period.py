from sqlalchemy import (
    BigInteger, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class ProrrogaPeriod(Base):
    """Periodo de Prórrogas de un semestre de core: cuándo se solicita y las dos fechas comunes de pago."""
    __tablename__ = "prorrogas_periods"

    id = Column(Integer, primary_key=True)
    period_id = Column(Integer, ForeignKey("core_academic_periods.id", ondelete="CASCADE"), nullable=False)
    opens_on = Column(Date, nullable=False)
    closes_on = Column(Date, nullable=False)
    payment_1_on = Column(Date, nullable=False)
    payment_2_on = Column(Date, nullable=False)
    updated_by_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="SET NULL"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    period = relationship("AcademicPeriod")

    __table_args__ = (
        UniqueConstraint("period_id", name="uq_prorrogas_periods_semestre"),
        CheckConstraint("closes_on > opens_on", name="ck_prorrogas_periods_ventana"),
        CheckConstraint("payment_1_on > opens_on AND payment_2_on > payment_1_on", name="ck_prorrogas_periods_pagos"),
        ExcludeConstraint((text("daterange(opens_on, closes_on, '[]')"), "&&"),
                          name="ex_prorrogas_periods_ventana", using="gist"),
    )
