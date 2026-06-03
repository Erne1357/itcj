"""Catálogo de las 9 fases del proceso de titulación (0–8)."""
from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.sql import text

from itcj2.models.base import Base


class PhaseDefinition(Base):
    """Definición catálogo de una fase. La instancia por proceso vive en ProcessPhase."""
    __tablename__ = "titulatec_phase_definitions"

    id = Column(Integer, primary_key=True)
    number = Column(Integer, unique=True, nullable=False)            # 0..8
    code = Column(String(40), unique=True, nullable=False)           # 'initial_docs', 'review_appointment', ...
    name = Column(String(120), nullable=False)
    responsible = Column(String(40), nullable=False)                 # 'student'|'school_services'|'titulaciones'|'vinculacion'|'synodals'
    icon = Column(String(40), nullable=True)                         # bootstrap-icon
    order_index = Column(Integer, nullable=False, server_default=text("0"))
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"), index=True)

    def __repr__(self) -> str:
        return f"<PhaseDefinition {self.number}:{self.code}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "number": self.number,
            "code": self.code,
            "name": self.name,
            "responsible": self.responsible,
            "icon": self.icon,
            "order_index": self.order_index,
            "is_active": self.is_active,
        }
