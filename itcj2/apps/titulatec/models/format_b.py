"""Formato B — 1-1 con proceso. Reemplaza al Tsoft."""
from sqlalchemy import (
    BigInteger, Column, Date, DateTime, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from itcj2.models.base import Base


class FormatB(Base):
    __tablename__ = "titulatec_format_b"

    process_id = Column(Integer, ForeignKey("titulatec_processes.id"), primary_key=True)

    # --- personal ---
    first_name = Column(String(120), nullable=True)
    last_name = Column(String(120), nullable=True)
    middle_name = Column(String(120), nullable=True)
    gender = Column(String(15), nullable=True)                      # male|female|unspecified
    age = Column(Integer, nullable=True)
    mobile_phone = Column(String(20), nullable=True)
    phone = Column(String(20), nullable=True)
    postal_code = Column(String(10), nullable=True)
    neighborhood = Column(String(120), nullable=True)
    street = Column(String(120), nullable=True)
    ext_number = Column(String(10), nullable=True)
    int_number = Column(String(10), nullable=True)

    # --- escolar ---
    control_number = Column(String(20), nullable=True)
    program_id = Column(Integer, ForeignKey("core_programs.id"), nullable=True)
    study_plan = Column(String(40), nullable=True)
    titulation_type = Column(String(60), nullable=True)             # espejo de modality
    admission_date = Column(Date, nullable=True)                    # primer mes del primer semestre
    graduation_date = Column(Date, nullable=True)                   # último mes del último semestre

    # --- proyecto ---
    project_name = Column(Text, nullable=True)

    # --- control ---
    status = Column(String(20), nullable=False, server_default=text("'draft'"))  # draft|submitted|approved|rejected
    approved_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    process = relationship("TitulationProcess", back_populates="format_b")

    def __repr__(self) -> str:
        return f"<FormatB p{self.process_id}:{self.status}>"
