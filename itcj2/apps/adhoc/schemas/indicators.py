"""Schemas Pydantic v2 del dominio **indicadores** de Adhoc (Calidad).

Tres recursos viven aquí:

* ``/indicator-years`` — el catálogo de años del tablero.
* ``/indicators``      — la ficha del indicador (16 campos + evidencia).
* ``/indicator-trackings`` — la celda de seguimiento por periodo.

Dos correcciones del legacy quedan codificadas en estos schemas:

1. **Los 4 umbrales son 4 campos.** ``api_indicators.save_indicators`` los
   empaquetaba en un solo string ``f"{blanco}-{rojo}-{amarillo}-{verde}"`` y el
   render los desempaquetaba con ``.split('-')`` — cualquier umbral con guion
   (``"1-2 días"``, ``"-5%"``) corrompía las cuatro celdas. Aquí son
   ``planned_white`` / ``planned_red`` / ``planned_yellow`` / ``planned_green``,
   exactamente como las 4 columnas de ``adhoc_indicators``.
2. **``frequency`` nunca vale ``""``.** El legacy escribía el ``value=""`` del
   ``<option>`` placeholder, que hoy rebotaría contra
   ``ck_adhoc_indicators_frequency``. :data:`IndicatorFrequencyField` lo coacciona
   a ``None`` antes de la validación de tipo (plan §2.8, reglas 1–3).

Nota sobre ``IndicatorUpdate``: el PATCH es multipart y el endpoint construye el
payload **solo con las claves que el cliente mandó**, así que
``model_dump(exclude_unset=True)`` distingue "no lo mandó" de "lo mandó vacío
para borrarlo". Un ``""`` explícito llega como ``None`` y limpia la columna.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from itcj2.apps.adhoc.schemas.common import (
    AdhocSchema,
    IndicatorFrequencyField,
    OptInt,
    OptStr,
    TrackingColorField,
)
from itcj2.apps.adhoc.utils.constants import (
    TRACKING_COLOR_DEFAULT,
    TRACKING_PERIODS_BY_FREQUENCY,
)

__all__ = [
    "IndicatorYearBulkCreate",
    "IndicatorYearOut",
    "IndicatorCreate",
    "IndicatorUpdate",
    "IndicatorOut",
    "IndicatorTrackingUpsert",
    "IndicatorTrackingOut",
    "MAX_TRACKING_PERIODS",
]

#: Cota superior absoluta de ``period_index`` cuando el indicador no declara
#: frecuencia. Es el máximo de :data:`TRACKING_PERIODS_BY_FREQUENCY` (52,
#: 'Semanal'), no un número mágico.
MAX_TRACKING_PERIODS: int = max(TRACKING_PERIODS_BY_FREQUENCY.values())

#: Año mínimo/máximo aceptados. El legacy hacía ``int(anio_val)`` sobre
#: **todos los valores del formulario** (fallback ``request.form.values()``),
#: así que un campo de texto cualquiera acababa como año.
_YEAR_MIN = 2000
_YEAR_MAX = 2100


# ==========================================================================
# Años
# ==========================================================================

class IndicatorYearBulkCreate(AdhocSchema):
    """``POST /indicator-years`` — alta de uno o varios años.

    Idempotente por diseño: los años que ya existen se reportan como omitidos,
    no como error (``adhoc_indicator_years.year`` es ``UNIQUE``).
    """

    # El rango va como **constraint** del elemento, no como un validador que
    # lanza: un ``raise ValueError`` dentro de un ``field_validator`` mete la
    # excepción original en el ``ctx`` del error, y el handler global de
    # ``RequestValidationError`` (itcj2/main.py) serializa ``exc.errors()`` tal
    # cual → ``TypeError: Object of type ValueError is not JSON serializable``,
    # o sea un 500 en vez del 422. Los constraints declarativos generan un
    # ``ctx`` que sí es JSON.
    years: list[Annotated[int, Field(ge=_YEAR_MIN, le=_YEAR_MAX)]] = Field(
        min_length=1, description=f"Años a dar de alta ({_YEAR_MIN}-{_YEAR_MAX})",
    )

    @field_validator("years")
    @classmethod
    def _dedupe(cls, values: list[int]) -> list[int]:
        """Deduplica preservando el orden de captura. No lanza."""
        return list(dict.fromkeys(values))


class IndicatorYearOut(BaseModel):
    """Un año del catálogo, con cuántos indicadores cuelgan de él."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    year: int
    indicators_count: int = 0

    @classmethod
    def from_model(cls, year, indicators_count: int = 0) -> "IndicatorYearOut":
        return cls(id=year.id, year=year.year, indicators_count=indicators_count)


# ==========================================================================
# Indicadores
# ==========================================================================

class IndicatorCreate(AdhocSchema):
    """Una fila del alta masiva del tablero (``POST /indicators``).

    ``year_id`` NO va aquí: es un campo suelto del multipart, común a todas las
    filas (el tablero siempre se captura dentro de un año).
    """

    process_id: int = Field(description="FK a adhoc_processes")

    objective: OptStr = Field(default=None, max_length=255)
    prev_results: OptStr = Field(default=None, max_length=255)
    unit_calc: OptStr = Field(default=None, max_length=255)
    responsible: OptStr = Field(default=None, max_length=255)
    facilitator: OptStr = Field(default=None, max_length=255)
    source: OptStr = Field(default=None, max_length=255)

    strategic_rel: OptStr = None
    criteria: OptStr = None
    plan_b: OptStr = None

    frequency: IndicatorFrequencyField = None

    planned_white: OptStr = Field(default=None, max_length=50)
    planned_red: OptStr = Field(default=None, max_length=50)
    planned_yellow: OptStr = Field(default=None, max_length=50)
    planned_green: OptStr = Field(default=None, max_length=50)


class IndicatorUpdate(AdhocSchema):
    """``PATCH /indicators/{id}`` — todos los campos opcionales.

    El endpoint solo pasa al service ``model_dump(exclude_unset=True)``, así que
    una clave ausente deja la columna intacta y una clave con ``""`` la limpia.
    ``process_id`` es la excepción: es ``NOT NULL``, así que mandarlo vacío es
    un error de validación del service, no un borrado.
    """

    process_id: OptInt = None

    objective: OptStr = Field(default=None, max_length=255)
    prev_results: OptStr = Field(default=None, max_length=255)
    unit_calc: OptStr = Field(default=None, max_length=255)
    responsible: OptStr = Field(default=None, max_length=255)
    facilitator: OptStr = Field(default=None, max_length=255)
    source: OptStr = Field(default=None, max_length=255)

    strategic_rel: OptStr = None
    criteria: OptStr = None
    plan_b: OptStr = None

    frequency: IndicatorFrequencyField = None

    planned_white: OptStr = Field(default=None, max_length=50)
    planned_red: OptStr = Field(default=None, max_length=50)
    planned_yellow: OptStr = Field(default=None, max_length=50)
    planned_green: OptStr = Field(default=None, max_length=50)


class IndicatorTrackingOut(BaseModel):
    """Una celda del renglón REAL del tablero de seguimiento."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    indicator_id: int
    period_index: int
    real_value: Optional[str] = None
    color: str = TRACKING_COLOR_DEFAULT


class IndicatorOut(BaseModel):
    """Ficha completa del indicador, con proceso resuelto y seguimiento.

    ``periods`` viaja en la respuesta para que la UI sepa cuántas columnas
    pintar sin duplicar el mapa de frecuencias en JS; es ``None`` cuando el
    indicador no declara frecuencia.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    year_id: int
    process_id: int
    process_name: Optional[str] = None
    process_color: Optional[str] = None

    objective: Optional[str] = None
    prev_results: Optional[str] = None
    unit_calc: Optional[str] = None
    responsible: Optional[str] = None
    facilitator: Optional[str] = None
    source: Optional[str] = None
    strategic_rel: Optional[str] = None
    criteria: Optional[str] = None
    plan_b: Optional[str] = None

    frequency: Optional[str] = None
    periods: Optional[int] = None

    planned_white: Optional[str] = None
    planned_red: Optional[str] = None
    planned_yellow: Optional[str] = None
    planned_green: Optional[str] = None

    document_url: Optional[str] = None
    has_document: bool = False

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    trackings: list[IndicatorTrackingOut] = Field(default_factory=list)

    @classmethod
    def from_model(cls, indicator, *, include_trackings: bool = True) -> "IndicatorOut":
        process = getattr(indicator, "process", None)
        trackings = []
        if include_trackings:
            trackings = [
                IndicatorTrackingOut.model_validate(t, from_attributes=True)
                for t in sorted(
                    getattr(indicator, "trackings", []) or [],
                    key=lambda t: t.period_index,
                )
            ]
        return cls(
            id=indicator.id,
            year_id=indicator.year_id,
            process_id=indicator.process_id,
            process_name=getattr(process, "name", None),
            process_color=getattr(process, "color", None),
            objective=indicator.objective,
            prev_results=indicator.prev_results,
            unit_calc=indicator.unit_calc,
            responsible=indicator.responsible,
            facilitator=indicator.facilitator,
            source=indicator.source,
            strategic_rel=indicator.strategic_rel,
            criteria=indicator.criteria,
            plan_b=indicator.plan_b,
            frequency=indicator.frequency,
            periods=TRACKING_PERIODS_BY_FREQUENCY.get(indicator.frequency or ""),
            planned_white=indicator.planned_white,
            planned_red=indicator.planned_red,
            planned_yellow=indicator.planned_yellow,
            planned_green=indicator.planned_green,
            document_url=indicator.document_url,
            has_document=bool(indicator.document_url),
            created_at=getattr(indicator, "created_at", None),
            updated_at=getattr(indicator, "updated_at", None),
            trackings=trackings,
        )


# ==========================================================================
# Seguimiento
# ==========================================================================

class IndicatorTrackingUpsert(AdhocSchema):
    """``PUT /indicator-trackings`` — upsert por ``(indicator_id, period_index)``.

    ``color`` es ``NOT NULL`` en BD y el legacy mandaba ``data.get('color')``
    sin fallback: :data:`TrackingColorField` resuelve ``None``/``""`` a
    ``'blanco'`` (plan §2.8, regla 5).

    El límite superior de ``period_index`` lo pone el service, que es quien
    conoce la frecuencia del indicador; aquí solo se rechaza lo absurdo.
    """

    indicator_id: int
    period_index: int = Field(ge=0, le=MAX_TRACKING_PERIODS)
    real_value: OptStr = Field(default=None, max_length=100)
    color: TrackingColorField = TRACKING_COLOR_DEFAULT
