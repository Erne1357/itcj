"""
Schemas Pydantic genéricos para catálogos simples de configuración (maint).

Reutilizables por MaintMaintenanceType y MaintServiceOrigin (y cualquier
catálogo futuro de estructura id/code/label/display_order/is_active).
"""
import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

_CODE_RE = re.compile(r'^[A-Z][A-Z0-9_]*$')


class CreateCatalogItem(BaseModel):
    """Crea un ítem de catálogo. `code` se normaliza a UPPER antes de validar."""
    code: str = Field(min_length=1, max_length=20)
    label: str = Field(min_length=1, max_length=60)
    display_order: Optional[int] = Field(default=0, ge=0)

    @field_validator("code")
    @classmethod
    def normalize_and_validate_code(cls, v: str) -> str:
        v = v.strip().upper()
        if not _CODE_RE.match(v):
            raise ValueError(
                "El code debe comenzar con una letra mayúscula y contener "
                "solo letras mayúsculas, dígitos o guiones bajos (A-Z, 0-9, _)"
            )
        return v

    @field_validator("label")
    @classmethod
    def strip_label(cls, v: str) -> str:
        return v.strip()


class UpdateCatalogItem(BaseModel):
    """Actualización parcial de un ítem. `code` no es modificable."""
    label: Optional[str] = Field(default=None, min_length=1, max_length=60)
    display_order: Optional[int] = Field(default=None, ge=0)

    @field_validator("label")
    @classmethod
    def strip_label(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v is not None else v


class ToggleCatalogItem(BaseModel):
    is_active: bool


class ReorderCatalogItem(BaseModel):
    id: int
    display_order: int = Field(ge=0)


class ReorderCatalog(BaseModel):
    order: list[ReorderCatalogItem]
