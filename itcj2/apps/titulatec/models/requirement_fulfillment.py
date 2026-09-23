"""Cumplimiento de un requisito de cotejo, por proceso.

Es la mitad que faltaba: `titulatec_cotejo_requirements` dice QUE se pide por
convocatoria; esta tabla dice QUIEN ya lo entrego.

AUSENCIA DE FILA = PENDIENTE. No hay estado 'pending' almacenado.
"""
from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.sql import text

from itcj2.models.base import Base


class RequirementFulfillment(Base):
    __tablename__ = "titulatec_requirement_fulfillments"
    __table_args__ = (
        UniqueConstraint("process_id", "requirement_id",
                         name="uq_titulatec_requirement_fulfillments_process_req"),
    )

    id = Column(BigInteger, primary_key=True)
    process_id = Column(Integer, ForeignKey("titulatec_processes.id"),
                        nullable=False, index=True)
    # RESTRICT y NO CASCADE: con CASCADE, borrar un requisito a media
    # convocatoria destruiria el credito de todos los que ya lo cumplieron y la
    # bitacora quedaria contradiciendo el estado. Misma regla que
    # `models/review_window.py:62-64`. La via soportada es `is_active = False`,
    # que ya existe en modelo, ruta, parcial y en el filtro `active_only=True`.
    requirement_id = Column(
        Integer,
        ForeignKey("titulatec_cotejo_requirements.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    requirement_code = Column(String(40), nullable=True)
    status = Column(String(20), nullable=False,
                    server_default=text("'fulfilled'"))     # fulfilled|waived|rejected
    source = Column(String(20), nullable=False)              # self_service|officer|system
    external_ref = Column(String(64), nullable=True)         # 'survey_response:1234'
    note = Column(Text, nullable=True)
    label_snapshot = Column(String(120), nullable=True)
    checked_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    fulfilled_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    def __repr__(self) -> str:
        return (f"<RequirementFulfillment p{self.process_id} "
                f"r{self.requirement_id} {self.status}>")
