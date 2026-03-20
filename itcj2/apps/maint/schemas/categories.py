from pydantic import BaseModel, Field
from typing import Optional


class CreateCategoryRequest(BaseModel):
    code: str = Field(min_length=3, max_length=50)
    name: str = Field(min_length=2, max_length=100)
    description: Optional[str] = None
    icon: Optional[str] = Field(default="bi-tools", max_length=50)
    field_template: Optional[list[dict]] = None
    display_order: Optional[int] = None


class UpdateCategoryRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    description: Optional[str] = None
    icon: Optional[str] = Field(default=None, max_length=50)
    display_order: Optional[int] = None


class ToggleCategoryRequest(BaseModel):
    is_active: bool


class UpdateFieldTemplateRequest(BaseModel):
    """Reemplaza el field_template completo de una categoría."""
    fields: list[dict] = []
    # Lista vacía → elimina el template (campos dinámicos desactivados)
