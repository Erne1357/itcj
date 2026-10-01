"""Constancia previa (spec §4.12): alumno que ya trae una liberacion de
encuesta o un no-adeudo de biblioteca de ANTES de este feature (otro
periodo, papel, sistema legado). Servicios Escolares la carga (por archivo o
a mano) y el servicio la aplica al proceso cuando el numero de control
coincide (`applied_process_id`/`applied_at`).

Puede llegar una fila SIN proceso que la reclame todavia (alumno que aun no
se inscribe a este periodo): por eso `applied_process_id` queda NULL hasta
que se aplica, y una vez aplicada no se vuelve a ofrecer. `issued_on` es
NULLABLE a proposito -- Review Focus #7 contempla constancias previas «sin
fecha»; las reglas de vigencia (fecha futura, 365/366 dias, sin fecha) viven
en el servicio (§4.2), no aqui.
"""
from sqlalchemy import (
    Column, Date, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.sql import text

from itcj2.models.base import Base

# Dominio de `kind`. 'survey' = liberacion de encuesta previa. 'library' =
# no adeudo de biblioteca previo.
PRIOR_KINDS = ("survey", "library")


class PriorClearance(Base):
    __tablename__ = "titulatec_prior_clearances"
    __table_args__ = (
        UniqueConstraint("kind", "control_number",
                         name="uq_titulatec_prior_clearances_kind_control"),
    )

    id = Column(Integer, primary_key=True)
    kind = Column(String(20), nullable=False)              # dominio: PRIOR_KINDS
    control_number = Column(String(20), nullable=False, index=True)
    issued_on = Column(Date, nullable=True)                 # NULL = sin fecha conocida
    note = Column(Text, nullable=True)
    source = Column(String(120), nullable=False)            # archivo/origen de la carga

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    applied_process_id = Column(Integer, ForeignKey("titulatec_processes.id"),
                                nullable=True)
    applied_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<PriorClearance {self.kind} {self.control_number}>"
