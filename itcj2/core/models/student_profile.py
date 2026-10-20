"""Perfil del alumno (1:1 con `core_users`).

Vive aparte de `core_users` porque esa tabla la comparten 7 apps: agregarle
columnas de titulacion la convierte en un cajon de sastre (riesgo 5 del spec).
La fila se crea PEREZOSAMENTE (`StudentProfileService.get_or_create`), nunca por
adelantado: no se migran los perfiles de los alumnos que ya existen.

`english_accredited` es TRI-ESTADO: NULL ("no sabemos") NO es lo mismo que False
("sabemos que no"). El formulario publico ni siquiera pregunta por el ingles.

`contact_email` es el correo PERSONAL, y `contact_email_verified_at` la fecha en
que su dueno abrio la liga de confirmacion (D17). `core_users.email` NO se toca
en ningun caso (D12).

PK = FK, como `titulatec_format_b.process_id`. Al ser la PK una llave foranea,
SQLAlchemy no la considera autoincremental y no emite BIGSERIAL — verificado
contra `titulatec_format_b.process_id`, que en la BD no tiene `column_default`.
"""
from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Integer, String, func,
)

from itcj2.models.base import Base


class StudentProfile(Base):
    __tablename__ = "core_student_profile"

    user_id = Column(
        BigInteger, ForeignKey("core_users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    english_accredited = Column(Boolean, nullable=True)          # tri-estado
    english_accredited_at = Column(Date, nullable=True)
    english_source = Column(String(20), nullable=True)           # sii|manual|import
    contact_email = Column(String(150), nullable=True, index=True)
    contact_email_verified_at = Column(DateTime, nullable=True)
    phone = Column(String(20), nullable=True)
    program_id = Column(Integer, ForeignKey("core_programs.id"), nullable=True)
    program_text = Column(String(160), nullable=True)
    reticula = Column(String(20), nullable=True)
    estatus_alumno = Column(String(40), nullable=True)
    campus = Column(String(60), nullable=True)
    curp = Column(String(18), nullable=True)
    has_efirma = Column(Boolean, nullable=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, onupdate=func.now())

    def __repr__(self) -> str:
        return f"<StudentProfile u{self.user_id}>"
