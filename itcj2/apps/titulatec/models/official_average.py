"""Promedio oficial por número de control, a la espera de que haya proceso.

Spec 2026-10-13-titulatec-promedios-design.md §3. Servicios Escolares entrega el
promedio de los egresados aunque todavía no tengan proceso; esta tabla es la
FUENTE y `titulatec_processes.final_average` su copia aplicada. Molde de
`PriorClearance`: lo que no tiene proceso se guarda aquí y se aplica al crearse
el proceso (`ImportService.import_rows`).

Escrita a mano junto con la migración `tt20261013b`: PK/FK sin nombre explícito
(toman el de Postgres, igual en `create_all` y en Alembic) y el CHECK con nombre
declarado en los dos lados, así que CI y dev/prod arman la misma tabla.
"""
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Numeric, String,
)
from sqlalchemy.sql import text

from itcj2.models.base import Base


class OfficialAverage(Base):
    __tablename__ = "titulatec_official_averages"

    # Número de control ya normalizado (`import_service.normalize_control`).
    control_number = Column(String(20), primary_key=True)
    average = Column(Numeric(5, 2), nullable=False)
    loaded_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True)
    loaded_at = Column(DateTime, nullable=False, server_default=text("NOW()"))

    # El cargador acepta 70-100 (mínimo aprobatorio); el CHECK de la tabla es la
    # misma red amplia (0-100) que la de `final_average`, por si algo la salta.
    __table_args__ = (
        CheckConstraint("average BETWEEN 0 AND 100",
                        name="ck_titulatec_official_averages_range"),
    )
