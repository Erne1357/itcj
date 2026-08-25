"""Schemas Pydantic v2 de los eventos de programa y sus adjuntos.

**Nota de vocabulario (plan §2.6):** aquí "programa" es un *evento del programa
de trabajo* de Calidad (el calendario del SGC), **no** una carrera académica
(eso es ``core_programs``).

Qué arregla este módulo respecto del legacy (``api_programs.py``):

- ``priority`` y ``status`` son ``Literal`` con default de schema, no ``str``.
  El legacy escribía ``None`` en ``priority`` cuando el radio no venía marcado
  (``api_programs.py:106``) y ``''`` desde los ``<select>`` placeholder: ambos
  reventarían hoy contra ``ck_adhoc_program_events_priority`` / ``_status``.
- Las 3 fechas son ``date``, no ``datetime`` (los inputs son ``type="date"``;
  el legacy declaraba ``DateTime`` aquí y ``Date`` en incidencias para el mismo
  concepto — ver plan §2.6).
- Una fecha mal formada ahora es un 422 con mensaje, no un ``ValueError`` que
  aborta el lote entero en silencio (``datetime.strptime`` sin ``try``).
- El alta masiva viaja con validación por fila: el legacy leía listas paralelas
  (``titles[]``, ``folios[]``, …) desalineables entre sí.

Los serializadores (``event_to_dict`` / ``file_to_dict``) viven aquí y son
funciones puras: no tocan la sesión, así que se testean sin BD. Asumen que las
relaciones ya vienen cargadas (el service usa ``selectinload``); si no lo
estuvieran, seguirían funcionando a costa de un lazy load.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Optional

from pydantic import Field

from itcj2.apps.adhoc.schemas.common import (
    AdhocSchema,
    OptInt,
    OptStr,
    PriorityField,
    blank_to_default,
)
from itcj2.apps.adhoc.utils.constants import (
    PROGRAM_EVENT_STATUS_DEFAULT,
    Priority,
    ProgramEventStatus,
)

__all__ = [
    "ProgramEventStatusField",
    "ProgramEventCreate",
    "ProgramEventBulkCreate",
    "ProgramEventUpdate",
    "ProgramEventFilters",
    "event_to_dict",
    "file_to_dict",
]


#: ``status`` es NOT NULL con CheckConstraint: un ``None``/``""`` entrante se
#: resuelve a ``'Planeado'`` ANTES de tocar el ORM (plan §2.8, regla 4).
ProgramEventStatusField = Annotated[
    ProgramEventStatus, blank_to_default(PROGRAM_EVENT_STATUS_DEFAULT)
]


# ==========================================================================
# Entrada
# ==========================================================================

class ProgramEventCreate(AdhocSchema):
    """Una fila del alta masiva de eventos de programa."""

    folio: Annotated[Optional[str], Field(max_length=50)] = None
    title: str = Field(..., min_length=1, max_length=200)
    description: OptStr = None

    start_date: Optional[date] = None
    commitment_date: Optional[date] = None
    real_date: Optional[date] = None

    priority: PriorityField = "Media"
    status: ProgramEventStatusField = PROGRAM_EVENT_STATUS_DEFAULT
    location: Annotated[Optional[str], Field(max_length=100)] = None

    category_id: OptInt = None
    area_id: OptInt = None
    process_id: OptInt = None
    responsible_id: OptInt = None


class ProgramEventBulkCreate(AdhocSchema):
    """Sobre del alta masiva: ``{"events": [ ... ]}``."""

    events: list[ProgramEventCreate] = Field(..., min_length=1)


class ProgramEventUpdate(AdhocSchema):
    """PATCH parcial. Se aplica con ``model_dump(exclude_unset=True)``.

    Un campo ausente no se toca; un campo con ``""`` o ``null`` **sí** limpia la
    columna (todas las nullables). ``priority`` y ``status`` son la excepción:
    son NOT NULL, así que un ``null`` explícito se ignora en el service en vez
    de reventar el UPDATE.
    """

    folio: Annotated[Optional[str], Field(max_length=50)] = None
    title: Annotated[Optional[str], Field(min_length=1, max_length=200)] = None
    description: OptStr = None

    start_date: Optional[date] = None
    commitment_date: Optional[date] = None
    real_date: Optional[date] = None

    priority: Optional[Priority] = None
    status: Optional[ProgramEventStatus] = None
    location: Annotated[Optional[str], Field(max_length=100)] = None

    category_id: OptInt = None
    area_id: OptInt = None
    process_id: OptInt = None
    responsible_id: OptInt = None


class ProgramEventFilters(AdhocSchema):
    """Filtros de ``GET /program-events`` (dependencia de query params).

    El legacy no filtraba nada en servidor: mandaba **todos** los eventos a la
    plantilla y filtraba por texto en el DOM (``programs.js::filtrarTabla``).
    """

    search: OptStr = None
    status: Optional[ProgramEventStatus] = None
    priority: Optional[Priority] = None
    category_id: OptInt = None
    area_id: OptInt = None
    process_id: OptInt = None
    responsible_id: OptInt = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None


# ==========================================================================
# Salida
# ==========================================================================

def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def file_to_dict(file: Any) -> dict:
    """Serializa un ``AdhocProgramEventFile``.

    ``id`` es la llave de descarga: el legacy construía la URL con el nombre de
    archivo crudo y sin ``encodeURIComponent`` (``programs.js:252``), así que
    cualquier nombre con espacio o acento daba 404.
    """
    return {
        "id": file.id,
        "event_id": file.event_id,
        "file_path": file.file_path,
        "original_name": file.original_name,
        "mime_type": file.mime_type,
        "size_bytes": file.size_bytes,
        "uploaded_by_id": file.uploaded_by_id,
        "created_at": _iso(getattr(file, "created_at", None)),
    }


def event_to_dict(event: Any, *, include_files: bool = False) -> dict:
    """Serializa un ``AdhocProgramEvent`` para la API y para las páginas."""
    category = getattr(event, "category", None)
    area = getattr(event, "area", None)
    process = getattr(event, "process", None)
    responsible = getattr(event, "responsible", None)
    files = list(getattr(event, "files", None) or [])

    data = {
        "id": event.id,
        "folio": event.folio,
        "title": event.title,
        "description": event.description,
        "start_date": _iso(event.start_date),
        "commitment_date": _iso(event.commitment_date),
        "real_date": _iso(event.real_date),
        "priority": event.priority,
        "status": event.status,
        "location": event.location,
        "category_id": event.category_id,
        "category_name": getattr(category, "name", None),
        "area_id": event.area_id,
        "area_name": getattr(area, "name", None),
        "area_color": getattr(area, "color", None),
        "process_id": event.process_id,
        "process_name": getattr(process, "name", None),
        "process_color": getattr(process, "color", None),
        "responsible_id": event.responsible_id,
        "responsible_name": getattr(responsible, "full_name", None),
        "files_count": len(files),
        "created_at": _iso(getattr(event, "created_at", None)),
        "updated_at": _iso(getattr(event, "updated_at", None)),
    }
    if include_files:
        data["files"] = [file_to_dict(f) for f in files]
    return data
