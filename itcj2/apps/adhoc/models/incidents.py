"""
Incidencias de Calidad.

Vocabulario de `status` resuelto (§2.5 del plan): el legacy tenía 3 valores en
conflicto (default `'Abierto'` nunca usado, UI con `No Iniciada|Iniciada|
Cerrada`, workflow escribiendo `'Completado'`). Canónico = el de la UI. El
workflow (`task_workflow_service`) debe escribir `'Cerrada'` aquí, nunca
`'Completado'` (ese valor es de `AdhocProgramEvent`).
"""
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class AdhocIncidentCategory(Base):
    __tablename__ = "adhoc_incident_categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<AdhocIncidentCategory {self.name}>"


class AdhocIncident(Base):
    __tablename__ = "adhoc_incidents"

    id = Column(Integer, primary_key=True)
    folio = Column(String(50), nullable=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    start_date = Column(Date, nullable=True)
    commitment_date = Column(Date, nullable=True)
    real_date = Column(Date, nullable=True)

    priority = Column(String(20), nullable=False, server_default=text("'Media'"))
    status = Column(String(50), nullable=False, server_default=text("'No Iniciada'"))

    category_id = Column(Integer, ForeignKey("adhoc_incident_categories.id"), nullable=True, index=True)
    area_id = Column(Integer, ForeignKey("adhoc_areas.id"), nullable=True, index=True)
    process_id = Column(Integer, ForeignKey("adhoc_processes.id"), nullable=True, index=True)
    responsible_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True, index=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    category = relationship("AdhocIncidentCategory")
    area = relationship("AdhocArea")
    process = relationship("AdhocProcess")
    responsible = relationship("User", foreign_keys=[responsible_id])

    __table_args__ = (
        CheckConstraint("priority IN ('Baja','Media','Alta','Urgente')",
                         name="ck_adhoc_incidents_priority"),
        CheckConstraint("status IN ('No Iniciada','Iniciada','Cerrada')",
                         name="ck_adhoc_incidents_status"),
    )

    def __repr__(self) -> str:
        return f"<AdhocIncident {self.folio or self.id}: {self.title}>"
