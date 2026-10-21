"""Perfil docente (grado y cédula) para el oficio de sinodales.

Un perfil por persona, compartido por todos sus departamentos.
"""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String
from sqlalchemy.sql import text

from itcj2.models.base import Base


class TeacherProfile(Base):
    __tablename__ = "titulatec_teacher_profiles"

    user_id = Column(BigInteger, ForeignKey("core_users.id"), primary_key=True)
    academic_degree = Column(String(150), nullable=False)
    professional_license = Column(String(20), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=True)
    updated_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)

    def __repr__(self) -> str:
        return f"<TeacherProfile u{self.user_id}>"
