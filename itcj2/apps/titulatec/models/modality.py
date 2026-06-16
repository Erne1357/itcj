"""Catálogo de modalidades de titulación."""
from sqlalchemy import Boolean, Column, Integer, JSON, String
from sqlalchemy.sql import text

from itcj2.models.base import Base


class Modality(Base):
    """Modalidad de titulación. Define reglas de firma y fases que se saltan."""
    __tablename__ = "titulatec_modalities"

    id = Column(Integer, primary_key=True)
    code = Column(String(40), unique=True, nullable=False)          # 'integral_residencias' | 'thesis' | 'research_project' | 'egel'
    name = Column(String(120), nullable=False)
    requires_synodals = Column(Boolean, nullable=False, server_default=text("TRUE"))
    signature_rule = Column(String(20), nullable=False, server_default=text("'president_only'"))  # 'president_only' | 'all_synodals'
    skips_phases = Column(JSON, nullable=True)                       # [4, 5] para EGEL
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"), index=True)

    def __repr__(self) -> str:
        return f"<Modality {self.code}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "requires_synodals": self.requires_synodals,
            "signature_rule": self.signature_rule,
            "skips_phases": self.skips_phases or [],
            "is_active": self.is_active,
        }
