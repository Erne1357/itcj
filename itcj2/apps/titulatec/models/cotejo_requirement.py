"""Requisitos de cotejo (qué llevar a la cita) configurables por convocatoria.

La jefa de Servicios Escolares define la lista por cohorte; el alumno la ve en su
cita y el encargado la usa como checklist para liberar/rechazar la fase 2.
"""
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text,
)
from sqlalchemy.sql import text

from itcj2.models.base import Base


class CotejoRequirement(Base):
    __tablename__ = "titulatec_cotejo_requirements"

    id = Column(Integer, primary_key=True)
    cohort_id = Column(
        Integer, ForeignKey("titulatec_cohorts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    label = Column(String(120), nullable=False)
    hint = Column(String(255), nullable=True)
    icon = Column(String(40), nullable=False, server_default=text("'check2-square'"))
    order_index = Column(Integer, nullable=False, server_default=text("0"))
    is_required = Column(Boolean, nullable=False, server_default=text("TRUE"))
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"), index=True)

    # Identidad estable del requisito, independiente del label que edite
    # Servicios Escolares. `auto_source` marca cual acredita el SISTEMA
    # ('graduate_survey' = la encuesta de egresados): un requisito con
    # `auto_source` no es borrable desde la UI ni editable en estos dos campos,
    # porque `create()` no puede fijarlos y no habria forma de restaurarlo.
    # Ambas NULL: no necesitan `server_default` sobre la tabla existente.
    code = Column(String(40), nullable=True, index=True)
    auto_source = Column(String(20), nullable=True)          # NULL | 'graduate_survey'

    # «Información para el alumno»: HTML con formato que escribe Servicios
    # Escolares en el editor del requisito y el alumno abre con el botón «i» de
    # su cita. Se guarda YA SANITIZADO (`utils/rich_text.sanitize_info_html`,
    # lista blanca) y las vistas lo vuelven a sanitizar al pintar: nunca se
    # pinta esta columna cruda. NULL = sin información = sin botón.
    info_html = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    def __repr__(self) -> str:
        return f"<CotejoRequirement c{self.cohort_id} {self.label!r}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "cohort_id": self.cohort_id,
            "label": self.label,
            "hint": self.hint,
            "icon": self.icon,
            "order_index": self.order_index,
            "is_required": self.is_required,
            "is_active": self.is_active,
            "info_html": self.info_html,
        }
