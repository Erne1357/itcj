from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base

payment_status_pg_enum = ENUM(
    "PENDING", "APPROVED", "MIDDLE", "NOPAID",
    name="payment_status_pg_enum",
    create_type=False,
)


#Pagos 

class Payments_pro(Base):
    __tablename__ = "prorrogas_payments"
    id = Column(BigInteger, primary_key=True)

    request_id = Column(BigInteger,ForeignKey("prorrogas_requests.id", ondelete="CASCADE", onupdate="CASCADE", ),nullable=False,)
    period_id = Column(Integer,ForeignKey("core_academic_periods.id", onupdate="CASCADE", ondelete="RESTRICT"),nullable=True,index=True,)
    num_payments_terms = Column(Integer)
    amount = Column(Numeric(10, 2))
    expiration_date = Column(DateTime)
    payday = Column(DateTime)
    status = Column(payment_status_pg_enum, nullable=False)
    admin_comment = Column(Text)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    
    request = relationship("Request_pro", back_populates="payments")


