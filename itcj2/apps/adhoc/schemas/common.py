"""Piezas compartidas por todos los schemas Pydantic v2 de Adhoc.

Tres cosas viven aquí:

1. **``empty_to_none``** — el coercionador que salva a la app del legacy. Los
   formularios del SGC mandan el ``value=""`` del ``<option>`` placeholder y el
   ``''`` de los inputs vacíos; sin coacción esos ``''`` llegarían a columnas
   con ``CheckConstraint`` (``frequency``, ``status``, ``priority``, ``color``)
   y a FKs enteras, reventando el INSERT. Ver plan §2.8.
2. **``PaginationParams``** — ``page``/``per_page`` acotados, para usar como
   dependencia de query en los tres listados paginados
   (``/documents``, ``/incidents``, ``/program-events``).
3. **``ok_item`` / ``ok_list`` / ``ok_page`` / ``ok_message``** — los cuatro
   sobres de respuesta de ``CLAUDE.md`` §3.2, escritos una sola vez para que
   los seis dominios no diverjan en el contrato.

Nada de esto habla con la BD ni con FastAPI (salvo el tipo de retorno): son
funciones puras, testeables sin cliente HTTP.
"""
from __future__ import annotations

from typing import Annotated, Any, Optional, Sequence, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from itcj2.apps.adhoc.utils.constants import (
    INDICATOR_FREQUENCIES,
    IndicatorFrequency,
    PRIORITY_DEFAULT,
    Priority,
    TRACKING_COLOR_DEFAULT,
    TrackingColor,
)

__all__ = [
    "empty_to_none",
    "EmptyToNone",
    "blank_to_default",
    "OptStr",
    "OptInt",
    "AdhocSchema",
    "PriorityField",
    "TrackingColorField",
    "IndicatorFrequencyField",
    "PaginationParams",
    "DEFAULT_PER_PAGE",
    "MAX_PER_PAGE",
    "ok_item",
    "ok_list",
    "ok_page",
    "ok_message",
]


# ==========================================================================
# 1. Coerción de vacíos
# ==========================================================================

def empty_to_none(value: Any) -> Any:
    """Convierte ``""`` y ``"   "`` en ``None``; deja pasar todo lo demás.

    Pensado para ``mode="before"``: corre **antes** de la validación de tipo,
    así que un ``""`` destinado a un ``int | None`` o a un ``Literal[...]`` se
    resuelve a ``None`` en vez de fallar con un mensaje ilegible.

    Uso directo en un campo::

        area_id: Annotated[Optional[int], BeforeValidator(empty_to_none)] = None

    …o, más corto, con los alias ``OptStr`` / ``OptInt`` de abajo, o heredando
    de :class:`AdhocSchema`, que lo aplica a todo el payload.
    """
    if isinstance(value, str) and not value.strip():
        return None
    return value


#: Anotación lista para componer: ``Annotated[X, EmptyToNone]``.
EmptyToNone = BeforeValidator(empty_to_none)

OptStr = Annotated[Optional[str], EmptyToNone]
OptInt = Annotated[Optional[int], EmptyToNone]


def blank_to_default(default: Any) -> BeforeValidator:
    """Validador ``mode="before"`` que resuelve ``None``/``""`` al ``default``.

    Es la regla 4 del plan §2.8: las columnas ``NOT NULL`` con
    ``CheckConstraint`` (``status``, ``priority``, ``color``) llevan default en
    el **schema**, no solo ``server_default`` en la BD, porque el legacy manda
    ``None`` de verdad (radio sin marcar, ``data.get('color')`` sin fallback) y
    un ``None`` explícito ignora el default de Pydantic.
    """
    def _coerce(value: Any) -> Any:
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        return value

    return BeforeValidator(_coerce)


#: Los tres campos cerrados que el legacy manda vacíos o nulos, ya blindados.
PriorityField = Annotated[Priority, blank_to_default(PRIORITY_DEFAULT)]
TrackingColorField = Annotated[TrackingColor, blank_to_default(TRACKING_COLOR_DEFAULT)]
IndicatorFrequencyField = Annotated[Optional[IndicatorFrequency], EmptyToNone]


class AdhocSchema(BaseModel):
    """Base de los schemas de Adhoc: recorta espacios y vacía a ``None``.

    El ``model_validator(mode="before")`` aplica :func:`empty_to_none` a **todo
    valor string del payload de primer nivel**, de modo que ningún schema tiene
    que acordarse de decorar campo por campo. Los campos requeridos siguen
    fallando (un ``""`` en un campo obligatorio se vuelve ``None`` → "field
    required"), que es exactamente lo que queremos: el legacy los aceptaba.

    Los campos con default cerrado (``priority``, ``color``, ``status``) deben
    usar además ``blank_to_default(...)``, porque este validador los deja en
    ``None`` y ``None`` no satisface un ``Literal``.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="ignore",
        populate_by_name=True,
    )

    @model_validator(mode="before")
    @classmethod
    def _blank_strings_to_none(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: empty_to_none(v) for k, v in data.items()}
        return data


# ==========================================================================
# 2. Paginación
# ==========================================================================

DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 200


class PaginationParams(BaseModel):
    """Query params de paginación. Se usa como dependencia, no como body::

        @router.get("")
        def list_documents(
            request: Request,
            pag: PaginationParams = Depends(),
            user: dict = require_perms("adhoc", ["adhoc.documents.api.read"]),
            db: DbSession = None,
        ):
            p = paginate(query, pag.page, pag.per_page)
            return ok_page(items, p, pag.page, pag.per_page)

    ``page`` es 1-based (igual que ``itcj2.models.base.paginate``). ``per_page``
    se acota a :data:`MAX_PER_PAGE` para que nadie pida la tabla entera con
    ``?per_page=100000``.
    """

    page: int = Field(default=1, ge=1, description="Página 1-based")
    per_page: int = Field(
        default=DEFAULT_PER_PAGE, ge=1, le=MAX_PER_PAGE,
        description=f"Elementos por página (máx. {MAX_PER_PAGE})",
    )

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page


# ==========================================================================
# 3. Sobres de respuesta
# ==========================================================================

T = TypeVar("T")


def ok_item(data: Any) -> dict:
    """``{"success": True, "data": {...}}`` — un solo recurso."""
    return {"success": True, "data": data}


def ok_list(items: Sequence[Any], total: Optional[int] = None) -> dict:
    """``{"success": True, "data": [...], "total": N}`` — lista sin paginar.

    ``total`` solo se pasa cuando el conteo real difiere de ``len(items)``
    (raro en listados sin paginación); si se omite se calcula.
    """
    items = list(items)
    return {"success": True, "data": items, "total": len(items) if total is None else total}


def ok_page(items: Sequence[Any], pagination, page: int, per_page: int) -> dict:
    """Sobre paginado a partir del ``Pagination`` de ``itcj2.models.base``.

    ``pagination`` es lo que devuelve ``paginate(query, page, per_page)``; de
    ahí salen ``total`` y ``total_pages`` (su atributo se llama ``pages``).
    """
    return {
        "success": True,
        "data": list(items),
        "total": pagination.total,
        "page": page,
        "per_page": per_page,
        "total_pages": pagination.pages,
    }


def ok_message(message: str) -> dict:
    """``{"success": True, "message": "..."}`` — operación sin payload."""
    return {"success": True, "message": message}


# Re-export cómodo: los dominios que solo necesitan el vocabulario de
# frecuencias para armar un <select> no tienen que importar constants aparte.
INDICATOR_FREQUENCY_CHOICES = INDICATOR_FREQUENCIES
