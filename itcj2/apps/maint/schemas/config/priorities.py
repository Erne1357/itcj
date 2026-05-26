"""
Schemas Pydantic para el CRUD de prioridades de configuración (maint).
"""
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class CreatePriority(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    label: str = Field(min_length=1, max_length=50)
    color: Optional[str] = Field(default=None, max_length=20)
    badge_class: Optional[str] = Field(default=None, max_length=50)
    sla_hours: int = Field(gt=0)
    is_default: Optional[bool] = False
    display_order: Optional[int] = Field(default=0, ge=0)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, v: str) -> str:
        return v.strip().upper()


class UpdatePriority(BaseModel):
    """Todos los campos opcionales; `code` no se puede editar."""
    label: Optional[str] = Field(default=None, min_length=1, max_length=50)
    color: Optional[str] = Field(default=None, max_length=20)
    badge_class: Optional[str] = Field(default=None, max_length=50)
    sla_hours: Optional[int] = Field(default=None, gt=0)
    is_default: Optional[bool] = None
    display_order: Optional[int] = Field(default=None, ge=0)


class TogglePriority(BaseModel):
    is_active: bool


class ReorderItem(BaseModel):
    id: int
    display_order: int = Field(ge=0)


class ReorderPriorities(BaseModel):
    order: list[ReorderItem]
