"""
Schemas Pydantic para el CRUD de prioridades de configuración del Helpdesk.
"""
from pydantic import BaseModel, Field
from typing import Optional


class CreatePriorityRequest(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    label: str = Field(min_length=2, max_length=50)
    color: Optional[str] = None
    badge_class: Optional[str] = None
    sla_hours: int = Field(gt=0, le=10000)
    display_order: Optional[int] = None


class UpdatePriorityRequest(BaseModel):
    label: Optional[str] = Field(default=None, min_length=2, max_length=50)
    color: Optional[str] = None
    badge_class: Optional[str] = None
    sla_hours: Optional[int] = Field(default=None, gt=0, le=10000)
    display_order: Optional[int] = None


class TogglePriorityRequest(BaseModel):
    is_active: bool


class ReorderPrioritiesRequest(BaseModel):
    order: list[dict]  # [{id: int, display_order: int}]
