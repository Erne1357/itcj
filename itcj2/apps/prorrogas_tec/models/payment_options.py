from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, Numeric, Text, Boolean
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base

#Opciones de pago 

class Payments_options(Base):
    __tablename__ = "prorrogas_payments_options"
    id = Column(BigInteger, primary_key=True)
    period_id = Column(Integer,ForeignKey("core_academic_periods.id", onupdate="CASCADE", ondelete="RESTRICT"),nullable=True,index=True,)
    total_payment = Column(Numeric(10, 2), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(Boolean, default= False)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    resquests = relationship("Request_pro", back_populates="paid_options")

    
