"""Cita de cotejo de documentos (fase 2, Servicios Escolares)."""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class ReviewAppointment(Base):
    __tablename__ = "titulatec_review_appointments"

    id = Column(Integer, primary_key=True)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"), nullable=False, index=True)
    scheduled_at = Column(DateTime, nullable=False)
    location = Column(String(120), nullable=True)                   # 'Edificio A · Servicios Escolares'
    status = Column(String(20), nullable=False, server_default=text("'scheduled'"))  # scheduled|confirmed|attended|rescheduled|no_show
    created_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=False)
    confirmed_at = Column(DateTime, nullable=True)
    note = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    process = relationship("TitulationProcess", back_populates="review_appointments")

    def __repr__(self) -> str:
        return f"<ReviewAppointment p{self.process_id} {self.status}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "process_id": self.process_id,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "location": self.location,
            "status": self.status,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "note": self.note,
        }
