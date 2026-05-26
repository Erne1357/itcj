"""
Schemas Pydantic para el CRUD de áreas técnicas de configuración (maint).
"""
import re
from typing import Optional
from pydantic import BaseModel, Field, field_validator


_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class CreateArea(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    label: str = Field(min_length=1, max_length=80)
    icon: Optional[str] = Field(default=None, max_length=60)
    color: Optional[str] = Field(default=None, max_length=20)
    description: Optional[str] = None
    display_order: Optional[int] = Field(default=0, ge=0)

    @field_validator("code")
    @classmethod
    def normalize_and_validate_code(cls, v: str) -> str:
        v = v.strip().upper()
        if not _CODE_RE.match(v):
            raise ValueError(
                "code debe comenzar con letra mayúscula y contener solo A-Z, 0-9 o _"
            )
        return v


class UpdateArea(BaseModel):
    """Todos los campos opcionales. El campo `code` nunca se modifica."""
    label: Optional[str] = Field(default=None, min_length=1, max_length=80)
    icon: Optional[str] = Field(default=None, max_length=60)
    color: Optional[str] = Field(default=None, max_length=20)
    description: Optional[str] = None
    display_order: Optional[int] = Field(default=None, ge=0)


class ToggleArea(BaseModel):
    is_active: bool


class ReorderAreaItem(BaseModel):
    id: int
    display_order: int = Field(ge=0)


class ReorderAreas(BaseModel):
    order: list[ReorderAreaItem]
