from pydantic import BaseModel, Field
from typing import Optional


class CreateCategoryRequest(BaseModel):
    area: str
    code: str = Field(min_length=3)
    name: str = Field(min_length=2)
    description: Optional[str] = None
    display_order: Optional[int] = None


class UpdateCategoryRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    display_order: Optional[int] = None


class ToggleCategoryRequest(BaseModel):
    is_active: bool


class ReorderCategoriesRequest(BaseModel):
    area: str
    order: list[dict]


class UpdateFieldTemplateRequest(BaseModel):
    enabled: bool
    fields: list[dict] = []
