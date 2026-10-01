"""Constancia previa DIFERIDA (spec §4.12): alumno que ya trae una
liberacion de encuesta o un no-adeudo de biblioteca de ANTES de este feature
(otro periodo, papel, sistema legado) y que todavia no tiene un proceso
abierto que la reciba. La carga la CLI `titulatec import-prior-clearances`
(`PriorClearanceService.import_rows`): con proceso abierto la constancia se
aplica de inmediato y NO pasa por esta tabla; sin el, se registra aqui y
`PriorClearanceService.apply_pending` la aplica sola cuando el alumno se
inscribe (`applied_process_id`/`applied_at`). Las constancias previas que
Biblioteca o Servicios Escolares registran a mano en su bandeja van directo
al proceso (`LibraryClearanceService.register_prior`), nunca aqui.

`applied_process_id` queda NULL hasta que se aplica, y una vez aplicada no
se vuelve a ofrecer -- salvo que llegue otra MAS NUEVA del mismo tipo y
numero de control: esa la reemplaza y vuelve a quedar pendiente (Ruling
R28). `issued_on` es NULLABLE en el esquema, pero NINGUN camino la deja en
NULL: el servicio exige la fecha (una fila sin fecha cae en «Invalidas») y
aplica las reglas de vigencia (fecha futura, 365/366 dias, §4.2).
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
    issued_on = Column(Date, nullable=True)                 # el servicio SIEMPRE la exige (ver docstring)
    note = Column(Text, nullable=True)
    source = Column(String(120), nullable=False)            # archivo/origen de la carga

    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    applied_process_id = Column(Integer, ForeignKey("titulatec_processes.id"),
                                nullable=True)
    applied_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<PriorClearance {self.kind} {self.control_number}>"
