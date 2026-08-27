"""
Eventos del programa de trabajo de Calidad.

Nota de vocabulario (§2.6 del plan): aquí "programa" = evento del programa de
trabajo de Calidad, **no** carrera académica (eso es `core_programs`). Se
conserva el vocabulario del legacy porque la UX no cambia; el prefijo
`adhoc_` elimina el riesgo de colisión con `core_programs`/`core_program_*`.

Las 3 fechas de `AdhocProgramEvent` son `Date` (verificado: los inputs son
`type="date"` en `incidents.js:184,189,194` y `programs.js:160,165`). El
legacy usaba `DateTime` aquí y `Date` en incidencias para el mismo concepto;
se unifica a `Date` en las dos.

`AdhocProgramEventFile` es tabla NUEVA (arregla el bug #18 del legacy: los
archivos de un evento se guardaban en disco y se "descubrían" con
`os.listdir`, sin registro en BD y sin borrarlos al eliminar el evento).
"""
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from itcj2.models.base import Base


class AdhocProgramCategory(Base):
    __tablename__ = "adhoc_program_categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<AdhocProgramCategory {self.name}>"


class AdhocProgramEvent(Base):
    __tablename__ = "adhoc_program_events"

    id = Column(Integer, primary_key=True)
    folio = Column(String(50), nullable=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    start_date = Column(Date, nullable=True)
    commitment_date = Column(Date, nullable=True)
    real_date = Column(Date, nullable=True)

    priority = Column(String(20), nullable=False, server_default=text("'Media'"))
    status = Column(String(50), nullable=False, server_default=text("'Planeado'"))
    location = Column(String(100), nullable=True)

    #: `programas.proj_id` del legacy. Negativo en los eventos placeholder.
    legacy_id = Column(Integer, nullable=True, unique=True)

    category_id = Column(Integer, ForeignKey("adhoc_program_categories.id"), nullable=True, index=True)
    area_id = Column(Integer, ForeignKey("adhoc_areas.id"), nullable=True, index=True)
    process_id = Column(Integer, ForeignKey("adhoc_processes.id"), nullable=True, index=True)
    responsible_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True, index=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    category = relationship("AdhocProgramCategory")
    area = relationship("AdhocArea")
    process = relationship("AdhocProcess")
    responsible = relationship("User", foreign_keys=[responsible_id])
    files = relationship(
        "AdhocProgramEventFile", back_populates="event", cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("priority IN ('Baja','Media','Alta','Urgente')",
                         name="ck_adhoc_program_events_priority"),
        CheckConstraint("status IN ('Planeado','En Proceso','Completado')",
                         name="ck_adhoc_program_events_status"),
    )

    def __repr__(self) -> str:
        return f"<AdhocProgramEvent {self.folio or self.id}: {self.title}>"


class AdhocProgramEventFile(Base):
    __tablename__ = "adhoc_program_event_files"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("adhoc_program_events.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    # Nullable: hay adjuntos del legacy cuyo registro existe pero cuyo binario
    # ya no esta en el servidor del proveedor. Se conserva el rastro.
    file_path = Column(String(255), nullable=True)   # ruta relativa "{event_id}/{filename}"
    original_name = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    uploaded_by_id = Column(BigInteger, ForeignKey("core_users.id"), nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    event = relationship("AdhocProgramEvent", back_populates="files")
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_id])

    def __repr__(self) -> str:
        return f"<AdhocProgramEventFile {self.original_name} (event={self.event_id})>"
