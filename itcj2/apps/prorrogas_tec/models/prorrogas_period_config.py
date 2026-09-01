from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base

# Periodos para realizar solicitudes
class ProrrogasPeriodConfig(Base):
    __tablename__ = "prorrogas_period_config"

    id = Column(Integer, primary_key=True)
    period_id = Column(Integer,ForeignKey("core_academic_periods.id", ondelete="CASCADE"),nullable=False,unique=True,)
    student_admission_start = Column(DateTime(timezone=True), nullable=False)
    student_admission_deadline = Column(DateTime(timezone=True), nullable=False)
    payment_1 = Column(DateTime)
    payment_2 = Column(DateTime)
    payment_3 = Column(DateTime)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)

    # Relaciones
    period = relationship("AcademicPeriod", back_populates="prorrogas_config")
    created_by = relationship("User", foreign_keys=[created_by_id])


    def __repr__(self) -> str:
        return f"<ProrrogasPeriodConfig period_id={self.period_id}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "period_id": self.period_id,
            "student_admission_start": self.student_admission_start.isoformat() if self.student_admission_start else None,
            "student_admission_deadline": self.student_admission_deadline.isoformat() if self.student_admission_deadline else None,
            "payment_1": self.payment_1,
            "payment_2": self.payment_2,
            "payment_3": self.payment_3,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by_id": self.created_by_id,
        }

    def is_student_window_open(self) -> bool:
        if not self.period:
            return False
        tz = ZoneInfo("America/Ciudad_Juarez")
        now = datetime.now(tz)
        return self.student_admission_start <= now <= self.student_admission_deadline