from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text,
)
from sqlalchemy.sql import text

from itcj2.models.base import Base

STATUSES = ("pendiente", "aceptada", "rechazada", "cancelada")
OPEN_STATUSES = ("pendiente", "aceptada")


class ProrrogaRequest(Base):
    """Solicitud de prórroga de un alumno en un semestre (spec §9)."""
    __tablename__ = "prorrogas_requests"

    id = Column(BigInteger, primary_key=True)
    origin = Column(String(10), nullable=False, server_default="app")
    import_ref = Column(String(80), unique=True)
    student_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="RESTRICT"))
    period_id = Column(Integer, ForeignKey("core_academic_periods.id", ondelete="RESTRICT"))
    period_label = Column(String(60))
    status = Column(String(20), nullable=False, server_default="pendiente")
    requested_terms = Column(SmallInteger)
    reason = Column(Text)
    control_number = Column(Text, nullable=False)
    student_name = Column(Text, nullable=False)
    program_name = Column(Text)
    program_level = Column(String(20))
    email = Column(Text)
    decided_by_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="SET NULL"))
    decided_at = Column(DateTime)
    decision_comment = Column(Text)
    total_amount = Column(Numeric(10, 2))
    plan_confirmed_at = Column(DateTime)
    plan_confirmed_by_id = Column(BigInteger, ForeignKey("core_users.id", ondelete="SET NULL"))
    block_exported_at = Column(DateTime)
    unblock_notified_at = Column(DateTime)
    last_reminded_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        CheckConstraint("origin IN ('app','excel')", name="ck_prorrogas_requests_origin"),
        CheckConstraint("origin = 'excel' OR student_id IS NOT NULL", name="ck_prorrogas_requests_student"),
        CheckConstraint("status IN ('pendiente','aceptada','rechazada','cancelada')",
                        name="ck_prorrogas_requests_status"),
        CheckConstraint("requested_terms BETWEEN 1 AND 3", name="ck_prorrogas_requests_terms"),
        CheckConstraint("total_amount IS NULL OR total_amount > 0", name="ck_prorrogas_requests_total"),
        Index("uq_prorrogas_requests_abierta", "student_id", "period_id", unique=True,
              postgresql_where=text("status IN ('pendiente','aceptada') AND origin = 'app'")),
        Index("ix_prorrogas_requests_estado", "status", "created_at"),
    )
