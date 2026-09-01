from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text
from sqlalchemy.dialects.postgresql import ENUM 
from itcj2.models.base import Base

request_status_pg_enum = ENUM(
    "PENDING", "APPROVED", "REJECTED",
    name="request_status_pg_enum",
    create_type=False,
)


# Solicitudes
class Request_pro(Base):
    __tablename__ = "prorrogas_requests"
    id = Column(BigInteger, primary_key=True)
    student_id = Column(BigInteger,ForeignKey("core_users.id", onupdate="CASCADE", ondelete="CASCADE"),nullable=False,)
    program_id = Column(Integer,ForeignKey("core_programs.id", onupdate="CASCADE", ondelete="CASCADE"),nullable=False,)
    period_id = Column(Integer,ForeignKey("core_academic_periods.id", onupdate="CASCADE", ondelete="RESTRICT"),nullable=True,index=True,)
    total_amount_id = Column(BigInteger,ForeignKey("prorrogas_payments_options.id", onupdate="CASCADE", ondelete="CASCADE"),nullable=False, default = 1)
    letter = Column(Text)
    payments_terms = Column(Integer, nullable=False) # Max 3
    status = Column(request_status_pg_enum, nullable=False, server_default="PENDING")


    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    payments = relationship(
        "Payments_pro",
        back_populates="request",
        cascade="all, delete-orphan",
        passive_deletes=True
    )
    student = relationship("User", foreign_keys=[student_id])
    career = relationship("Program", foreign_keys=[program_id])

    period = relationship("AcademicPeriod")

    paid_options = relationship("Payments_options", back_populates="resquests")
