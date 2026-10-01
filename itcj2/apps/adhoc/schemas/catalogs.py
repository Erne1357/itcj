"""Schemas Pydantic v2 de los **seis catálogos simples** de Adhoc (Calidad).

``/areas`` · ``/processes`` · ``/document-categories`` ·
``/document-classifications`` · ``/incident-categories`` · ``/program-categories``.

Los seis comparten el mismo esqueleto (``id`` + ``name`` UNIQUE + timestamps);
área y proceso añaden ``color``, área añade ``is_active`` y proceso añade
``description``. Por eso los cuatro catálogos de solo-nombre reusan un único
trío de schemas (:class:`NamedCatalogCreate` / :class:`NamedCatalogUpdate` /
:class:`NamedCatalogOut`) en vez de cuatro copias.

Decisiones que vienen del legacy (``docs/adhoc/analysis/src_api.md`` §1.1, §1.2,
§2.4 y el plan §2.8, §7):

* **Alta masiva con envoltorio ``items``.** El legacy mandaba listas paralelas
  (``nombres[]`` + ``colores[]`` en form-data, o ``{"nombres": [...]}`` en JSON
  para las categorías de programa): tres contratos distintos para la misma
  operación, y un ``zip()`` que descartaba en silencio el sobrante si las dos
  listas venían desalineadas. Aquí hay **uno solo**:
  ``{"items": [{...}, {...}]}``, con cada elemento validado por separado.
* **``color`` es un hex ``#RRGGBB`` validado.** El legacy lo aceptaba sin
  mirarlo (y en ``Process`` lo escribía dentro de ``description``); la columna
  es ``String(7)``, así que un valor más largo reventaba en el INSERT.
* **``is_active`` de área es un campo de verdad.** El legacy filtraba por él
  sin exponerlo, y las filas insertadas por SQL quedaban ``NULL`` → invisibles.
* Todo hereda de :class:`~itcj2.apps.adhoc.schemas.common.AdhocSchema`, que
  recorta espacios y convierte ``""`` en ``None`` antes de validar el tipo —
  la regla 2 del plan §2.8. Los campos ``NOT NULL`` con default
  (``color``, ``is_active``) usan además ``blank_to_default(...)`` para que un
  ``""`` del formulario se resuelva al default en vez de quedar en ``None``.

Los ``*Update`` **no** rechazan aquí un ``name`` explícitamente vacío: se dejan
pasar como ``None`` y es el service quien responde con un mensaje humano
(``«name» no puede quedar vacío`` → 400). Así la regla vive en un solo sitio y
vale también para los llamadores que no pasan por HTTP.
"""
from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field

from itcj2.apps.adhoc.schemas.common import AdhocSchema, OptStr, blank_to_default

__all__ = [
    "HEX_COLOR_PATTERN",
    "HexColor",
    "OptHexColor",
    "MAX_BULK_ITEMS",
    "AREA_COLOR_DEFAULT",
    "PROCESS_COLOR_DEFAULT",
    "AreaCreate",
    "AreaUpdate",
    "AreaOut",
    "AreaBulkCreate",
    "ProcessCreate",
    "ProcessUpdate",
    "ProcessOut",
    "ProcessBulkCreate",
    "NamedCatalogCreate",
    "NamedCatalogUpdate",
    "NamedCatalogOut",
    "NamedCatalogBulkCreate",
]

#: ``#RRGGBB`` — lo único que cabe en la columna ``String(7)``.
HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"

#: Tope de elementos por alta masiva. El legacy no tenía ninguno: un formulario
#: con 50 000 filas se traducía en 50 000 INSERT dentro de una transacción.
MAX_BULK_ITEMS = 200

#: Mismos valores que el ``server_default`` de las columnas.
AREA_COLOR_DEFAULT = "#4834d4"
PROCESS_COLOR_DEFAULT = "#b2bec3"

#: ``name`` es ``String(100)`` y ``UNIQUE`` en los seis catálogos.
CatalogName = Annotated[str, Field(min_length=1, max_length=100)]

#: Hex obligatorio con default: un ``""`` del ``<input type=color>`` vacío se
#: resuelve al default en vez de reventar contra el patrón. La restricción va
#: SIEMPRE sobre el ``str`` (nunca sobre el ``Optional``): en Pydantic v2 un
#: ``pattern`` colgado de un ``Optional[str]`` no se aplica al miembro correcto.
HexColor = Annotated[str, Field(pattern=HEX_COLOR_PATTERN)]
OptHexColor = Optional[HexColor]
AreaColor = Annotated[HexColor, blank_to_default(AREA_COLOR_DEFAULT)]
ProcessColor = Annotated[HexColor, blank_to_default(PROCESS_COLOR_DEFAULT)]


class _CatalogOutBase(BaseModel):
    """Parte común de la respuesta: lo que tienen los seis."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    updated_at: datetime


# ==========================================================================
# Áreas — nombre + color + is_active
# ==========================================================================

class AreaCreate(AdhocSchema):
    """Un elemento del alta masiva de ``POST /areas``."""

    name: CatalogName
    color: AreaColor = AREA_COLOR_DEFAULT
    is_active: Annotated[bool, blank_to_default(True)] = True


class AreaUpdate(AdhocSchema):
    """``PATCH /areas/{id}`` — todo opcional, se aplica solo lo enviado."""

    name: Optional[CatalogName] = None
    color: OptHexColor = None
    is_active: Optional[bool] = None


class AreaOut(_CatalogOutBase):
    color: str
    is_active: bool


class AreaBulkCreate(AdhocSchema):
    items: list[AreaCreate] = Field(min_length=1, max_length=MAX_BULK_ITEMS)


# ==========================================================================
# Procesos — nombre + color (columna real) + description (texto libre)
# ==========================================================================

class ProcessCreate(AdhocSchema):
    """Un elemento del alta masiva de ``POST /processes``.

    ``color`` y ``description`` son campos independientes: el legacy los
    fusionaba (``Process(name=..., description=color)``).
    """

    name: CatalogName
    color: ProcessColor = PROCESS_COLOR_DEFAULT
    description: OptStr = None


class ProcessUpdate(AdhocSchema):
    """``PATCH /processes/{id}``. Un ``description`` vacío **sí** limpia la
    columna (es ``nullable``); un ``name`` o un ``color`` vacío es un error."""

    name: Optional[CatalogName] = None
    color: OptHexColor = None
    description: OptStr = None


class ProcessOut(_CatalogOutBase):
    color: str
    description: Optional[str] = None


class ProcessBulkCreate(AdhocSchema):
    items: list[ProcessCreate] = Field(min_length=1, max_length=MAX_BULK_ITEMS)


# ==========================================================================
# Catálogos de solo nombre
# (document-categories, document-classifications,
#  incident-categories, program-categories)
# ==========================================================================

class NamedCatalogCreate(AdhocSchema):
    name: CatalogName


class NamedCatalogUpdate(AdhocSchema):
    name: Optional[CatalogName] = None


class NamedCatalogOut(_CatalogOutBase):
    pass


class NamedCatalogBulkCreate(AdhocSchema):
    items: list[NamedCatalogCreate] = Field(min_length=1, max_length=MAX_BULK_ITEMS)
