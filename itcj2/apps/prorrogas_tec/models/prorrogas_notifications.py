from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer,Text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


#Notificaciones

class Notifications(Base):
    __tablename__ = "prorrogas_notifications"
    id = Column(BigInteger, primary_key=True)
    student_id = Column(BigInteger,ForeignKey("core_users.id", onupdate="CASCADE", ondelete="CASCADE"),nullable=False,)
    message = Column(Text)
    period_id = Column(Integer,ForeignKey("core_academic_periods.id", onupdate="CASCADE", ondelete="RESTRICT"),nullable=True,index=True,)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))






