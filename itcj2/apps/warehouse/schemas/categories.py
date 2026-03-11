from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Categorías ────────────────────────────────────────────────────────────────

class WarehouseCategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: Optional[str] = None
    icon: str = Field(default="bi-box-seam", max_length=50)
    # NULL = categoría global (visible para todos los admins del almacén)
    department_code: Optional[str] = Field(default=None, max_length=50)
    display_order: int = Field(default=0, ge=0)


class WarehouseCategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    description: Optional[str] = None
    icon: Optional[str] = Field(default=None, max_length=50)
    display_order: Optional[int] = Field(default=None, ge=0)


class WarehouseCategoryOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    icon: str
    department_code: Optional[str]
    is_active: bool
    display_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Subcategorías ─────────────────────────────────────────────────────────────

class WarehouseSubcategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: Optional[str] = None
    display_order: int = Field(default=0, ge=0)


class WarehouseSubcategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    description: Optional[str] = None
    display_order: Optional[int] = Field(default=None, ge=0)


class WarehouseSubcategoryOut(BaseModel):
    id: int
    category_id: int
    name: str
    description: Optional[str]
    is_active: bool
    display_order: int
    created_at: datetime

    model_config = {"from_attributes": True}


class WarehouseCategoryWithSubsOut(WarehouseCategoryOut):
    """Categoría con sus subcategorías anidadas."""
    subcategories: list[WarehouseSubcategoryOut] = []
