"""Schemas Pydantic para el catálogo de prendas de VisteTec."""
from typing import Optional
from pydantic import BaseModel, Field


class CatalogListParams(BaseModel):
    page: int = Field(1, ge=1)
    per_page: int = Field(12, ge=1, le=50)
    category: Optional[str] = None
    gender: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None
    condition: Optional[str] = None
    search: Optional[str] = None
