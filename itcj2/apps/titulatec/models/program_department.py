"""Carrera -> departamento académico y datos de membrete del oficio."""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String

from itcj2.models.base import Base


class ProgramDepartment(Base):
    __tablename__ = "titulatec_program_departments"

    program_id = Column(Integer, ForeignKey("core_programs.id"), primary_key=True)
    department_id = Column(Integer, ForeignKey("core_departments.id"), nullable=False, index=True)
    official_name = Column(String(200), nullable=True)
    updated_at = Column(DateTime, nullable=True)
    updated_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)

    def __repr__(self) -> str:
        return f"<ProgramDepartment prog{self.program_id} dept{self.department_id}>"


class DepartmentSettings(Base):
    __tablename__ = "titulatec_department_settings"

    department_id = Column(Integer, ForeignKey("core_departments.id"), primary_key=True)
    oficio_header = Column(String(200), nullable=False)
    addressee_position_code = Column(String(60), nullable=False)
    attn_position_code = Column(String(60), nullable=True)
    updated_at = Column(DateTime, nullable=True)
    updated_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)

    def __repr__(self) -> str:
        return f"<DepartmentSettings dept{self.department_id}>"
