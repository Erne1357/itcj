"""Schemas Pydantic v2 de **incidencias** (``/api/adhoc/v2/incidents``).

Aquí se cierran cuatro agujeros del legacy (``routes/api/api_incidents.py``):

1. **``status`` tenía cuatro vocabularios en conflicto.** El modelo declaraba
   default ``'Abierto'`` (nunca usado), la UI ofrecía
   ``No Iniciada|Iniciada|Cerrada`` y el motor de workflow escribía
   ``'Completado'``. El canónico es el de la UI y ya vive en el
   ``CheckConstraint`` ``ck_adhoc_incidents_status``; aquí se declara como
   ``Literal``, así que un valor fuera del vocabulario es un **422**, no un
   ``IntegrityError`` a mitad del lote.
2. **``priority`` es ``NOT NULL``** y el legacy mandaba ``None`` en cuanto el
   radio no venía marcado (``request.form.get('priorities[1]')``, con el índice
   1 hardcodeado). Se resuelve al default ``'Media'`` **en el schema**
   (``blank_to_default``), de modo que ningún ``None`` llega al ORM.
3. **Las tres fechas son ``Date``.** El legacy hacía
   ``datetime.strptime(x, '%Y-%m-%d')`` **sin** ``.date()`` en la ruta de
   edición (guardaba un ``datetime`` en una columna ``Date``) y **con**
   ``.date()`` en la de alta. Pydantic parsea a ``datetime.date`` en las dos.
4. **El alta masiva leía 10 listas paralelas** e iteraba por índice, con un
   índice 1-based solo para ``priorities``. Aquí el cuerpo es una
   ``list[IncidentCreate]``: cruzar datos entre registros es imposible por
   construcción. Para el cliente que aún mande listas paralelas,
   :class:`IncidentBulkCreate` las adapta **exigiendo que todas midan lo
   mismo**; si no cuadran, 422 explícito en vez de datos cruzados en silencio.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from itcj2.apps.adhoc.schemas.common import (
    AdhocSchema,
    OptInt,
    OptStr,
    blank_to_default,
)
from itcj2.apps.adhoc.utils.constants import (
    INCIDENT_STATUS_DEFAULT,
    IncidentStatus,
    PRIORITY_DEFAULT,
    Priority,
)

__all__ = [
    "IncidentCreate",
    "IncidentBulkCreate",
    "IncidentUpdate",
    "IncidentRefOut",
    "IncidentUserRefOut",
    "IncidentOut",
    "serialize_incident",
    "file_to_dict",
    "MAX_BULK_ITEMS",
]

MAX_BULK_ITEMS = 200

#: ``priority`` / ``status`` son ``NOT NULL`` con ``CheckConstraint``: un
#: ``None`` o un ``""`` entrante se resuelve al default ANTES de tocar el ORM
#: (plan §2.8, regla 4).
PriorityIn = Annotated[Priority, blank_to_default(PRIORITY_DEFAULT)]
IncidentStatusIn = Annotated[IncidentStatus, blank_to_default(INCIDENT_STATUS_DEFAULT)]


# ==========================================================================
# Entrada
# ==========================================================================

class IncidentCreate(AdhocSchema):
    """Una incidencia del alta masiva. Solo ``title`` es obligatorio."""

    title: str = Field(min_length=1, max_length=200)
    folio: OptStr = Field(default=None, max_length=50)
    description: OptStr = None

    start_date: Optional[date] = None
    commitment_date: Optional[date] = None
    real_date: Optional[date] = None

    priority: PriorityIn = PRIORITY_DEFAULT
    status: IncidentStatusIn = INCIDENT_STATUS_DEFAULT

    category_id: OptInt = None
    area_id: OptInt = None
    process_id: OptInt = None
    responsible_id: OptInt = None


class IncidentUpdate(AdhocSchema):
    """PATCH parcial: solo se aplica lo que venga en el cuerpo.

    El service usa ``model_dump(exclude_unset=True)``, así que un campo ausente
    se queda como está y un ``null`` explícito **sí** limpia la columna (las
    FKs, el folio, la descripción y las fechas son nullable). ``priority`` y
    ``status`` son la excepción: son ``NOT NULL``, así que un ``null``/``""``
    explícito se resuelve al default en vez de propagarse.
    """

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    folio: OptStr = Field(default=None, max_length=50)
    description: OptStr = None

    start_date: Optional[date] = None
    commitment_date: Optional[date] = None
    real_date: Optional[date] = None

    # El default ``None`` solo marca "campo ausente"; nunca se valida contra el
    # Literal porque Pydantic no valida defaults. En cuanto la clave viene en
    # el cuerpo, ``blank_to_default`` garantiza un valor del vocabulario.
    priority: PriorityIn = None  # type: ignore[assignment]
    status: IncidentStatusIn = None  # type: ignore[assignment]

    category_id: OptInt = None
    area_id: OptInt = None
    process_id: OptInt = None
    responsible_id: OptInt = None


#: Mapa listas-paralelas del legacy -> campo de :class:`IncidentCreate`.
#: Se aceptan con y sin el sufijo ``[]`` que usaban los ``name`` del form.
_PARALLEL_KEYS: dict[str, str] = {
    "folios": "folio",
    "titles": "title",
    "descriptions": "description",
    "start_dates": "start_date",
    "commitment_dates": "commitment_date",
    "real_dates": "real_date",
    "priorities": "priority",
    "statuses": "status",
    "category_ids": "category_id",
    "area_ids": "area_id",
    "process_ids": "process_id",
    "responsible_ids": "responsible_id",
}


class IncidentBulkCreate(BaseModel):
    """Cuerpo de ``POST /incidents``: ``{"items": [ {...}, {...} ]}``.

    Acepta además el formato de listas paralelas del legacy
    (``{"titles": [...], "priorities": [...]}``) **solo si todas las listas
    miden lo mismo**. El legacy iteraba ``range(len(titles))`` y leía cada otra
    lista con un ``get_safe`` que devolvía ``None`` fuera de rango: una lista
    corta no era un error, era un campo silenciosamente vacío en el registro
    equivocado. Aquí eso es un 422 con el detalle de qué lista descuadra.
    """

    model_config = ConfigDict(extra="ignore")

    items: list[IncidentCreate] = Field(min_length=1, max_length=MAX_BULK_ITEMS)

    @model_validator(mode="before")
    @classmethod
    def _accept_parallel_lists(cls, data: Any) -> Any:
        if not isinstance(data, dict) or data.get("items") is not None:
            return data

        # Normaliza "titles[]" -> "titles" y quédate solo con lo reconocible.
        lists: dict[str, list] = {}
        for raw_key, value in data.items():
            key = raw_key[:-2] if raw_key.endswith("[]") else raw_key
            field = _PARALLEL_KEYS.get(key)
            if field is None or not isinstance(value, (list, tuple)):
                continue
            lists[field] = list(value)

        if "title" not in lists:
            # Ni ``items`` ni listas paralelas: que falle como "field required".
            return data

        expected = len(lists["title"])
        descuadre = {f: len(v) for f, v in lists.items() if len(v) != expected}
        if descuadre:
            detalle = ", ".join(f"{f}={n}" for f, n in sorted(descuadre.items()))
            # PydanticCustomError, no ValueError: el manejador global de
            # RequestValidationError (``itcj2/main.py``) serializa
            # ``exc.errors()`` con ``json.dumps``, y un ``ValueError`` crudo
            # viaja dentro de ``ctx['error']`` -> "Object of type ValueError is
            # not JSON serializable" -> 500 en vez del 422 que toca.
            raise PydanticCustomError(
                "parallel_lists_length_mismatch",
                "Las listas paralelas deben tener la misma longitud que 'titles' "
                "({expected}); descuadran: {detalle}",
                {"expected": expected, "detalle": detalle},
            )

        return {
            "items": [
                {field: values[i] for field, values in lists.items()}
                for i in range(expected)
            ]
        }


# ==========================================================================
# Salida
# ==========================================================================

class IncidentRefOut(BaseModel):
    """Catálogo referenciado (categoría, área, proceso)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class IncidentUserRefOut(BaseModel):
    """Responsable. ``full_name`` es la hybrid property de ``core_users``."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str


class IncidentOut(BaseModel):
    """Incidencia tal como la ve el cliente."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    folio: Optional[str] = None
    title: str
    description: Optional[str] = None

    start_date: Optional[date] = None
    commitment_date: Optional[date] = None
    real_date: Optional[date] = None

    priority: str
    status: str

    category_id: Optional[int] = None
    area_id: Optional[int] = None
    process_id: Optional[int] = None
    responsible_id: Optional[int] = None

    category: Optional[IncidentRefOut] = None
    area: Optional[IncidentRefOut] = None
    process: Optional[IncidentRefOut] = None
    responsible: Optional[IncidentUserRefOut] = None

    #: Cuántas tareas cuelgan de la incidencia (columna "Tareas" de la tabla).
    #: Lo calcula el service en UNA query agrupada, no una por fila.
    task_count: int = 0

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


def serialize_incident(incident: Any, *, task_count: Optional[int] = None) -> dict:
    """ORM -> ``dict`` listo para JSON (fechas en ISO)."""
    out = IncidentOut.model_validate(incident).model_dump(mode="json")
    if task_count is not None:
        out["task_count"] = task_count
    return out


def file_to_dict(file: Any) -> dict:
    """Serializa un ``AdhocIncidentFile``. Espejo de ``programs.file_to_dict``.

    ``is_available`` es lo único que no tiene equivalente en eventos de
    programa: distingue los adjuntos migrados cuyo ``file_path`` es ``NULL``
    (51 de los 351 del SGC legacy — el binario ya no está en el servidor del
    proveedor) de los que sí se pueden descargar. El listado los muestra
    igual, marcados como no disponibles, en vez de perder el rastro de qué se
    adjuntó.
    """
    return {
        "id": file.id,
        "incident_id": file.incident_id,
        "file_path": file.file_path,
        "original_name": file.original_name,
        "mime_type": file.mime_type,
        "size_bytes": file.size_bytes,
        "uploaded_by_id": file.uploaded_by_id,
        "is_available": bool(file.file_path),
        "created_at": (
            file.created_at.isoformat()
            if isinstance(getattr(file, "created_at", None), (date, datetime))
            else None
        ),
    }
