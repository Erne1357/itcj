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

    #: `proyectos.proj_id` del legacy. Idempotencia del ETL y trazabilidad.
    #: Negativo en las incidencias placeholder que rescatan tareas cuyo padre
    #: fue borrado del legacy.
    legacy_id = Column(Integer, nullable=True, unique=True)

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


class AdhocIncidentFile(Base):
    """Adjunto de una incidencia (no conformidad).

    En ISO 9001 el expediente de una no conformidad ES la evidencia, así que el
    legacy guardaba 409 archivos en ``inci_files`` y el esquema nuevo no tenía
    dónde ponerlos. Espejo de :class:`AdhocProgramEventFile`.

    ``file_path`` es nullable a propósito: parte de los adjuntos del legacy
    existen como registro pero su binario ya no está en el servidor del
    proveedor. Se conserva el rastro (qué se adjuntó y quién) marcando el
    archivo como no disponible, en vez de perder la fila entera. (Cuántos son
    exactamente es un dato de la base, no del modelo: escribirlo aquí lo
    convierte en una cifra que caduca sin que nada lo note.)
    """
    __tablename__ = "adhoc_incident_files"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("adhoc_incidents.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    file_path = Column(String(255), nullable=True)   # ruta relativa "{incident_id}/{filename}"
    original_name = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    uploaded_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    incident = relationship("AdhocIncident", foreign_keys=[incident_id])
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_id])

    def __repr__(self) -> str:
        return f"<AdhocIncidentFile {self.original_name} (incident={self.incident_id})>"
