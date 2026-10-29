from sqlalchemy import (
    BigInteger, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Numeric, SmallInteger, String, Text,
)
from sqlalchemy.sql import text

from itcj2.models.base import Base


class ProrrogaInstallment(Base):
    """Parcialidad del plan de pago de una solicitud aceptada; al cambiar el plan se marca `superseded_at`."""
    __tablename__ = "prorrogas_installments"

    id = Column(BigInteger, primary_key=True)
    request_id = Column(BigInteger, ForeignKey("prorrogas_requests.id", ondelete="CASCADE"), nullable=False)
    number = Column(SmallInteger, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    due_date = Column(Date, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    superseded_at = Column(DateTime)

    __table_args__ = (
        CheckConstraint("number BETWEEN 1 AND 3", name="ck_prorrogas_installments_number"),
        CheckConstraint("amount > 0", name="ck_prorrogas_installments_amount"),
        Index("uq_prorrogas_installments_vigente", "request_id", "number", unique=True,
              postgresql_where=text("superseded_at IS NULL")),
    )


class ProrrogaPayment(Base):
    """Recibo de Caja: lo captura la secretaria (app) o llega del Excel (folio)."""
    __tablename__ = "prorrogas_payments"

    id = Column(BigInteger, primary_key=True)
    request_id = Column(BigInteger, ForeignKey("prorrogas_requests.id", ondelete="CASCADE"), nullable=False)
    origin = Column(String(10), nullable=False, server_default="app")
    folio = Column(String(40))
    paid_on = Column(Date, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    recorded_by_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="SET NULL"))
    recorded_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    voided_at = Column(DateTime)
    voided_by_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="SET NULL"))
    void_reason = Column(Text)

    __table_args__ = (
        CheckConstraint("origin IN ('app','excel')", name="ck_prorrogas_payments_origin"),
        CheckConstraint("amount > 0", name="ck_prorrogas_payments_amount"),
        Index("uq_prorrogas_payments_folio_vigente", "folio", unique=True,
              postgresql_where=text("folio IS NOT NULL AND voided_at IS NULL")),
        Index("ix_prorrogas_payments_solicitud", "request_id"),
    )
