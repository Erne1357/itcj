"""
Schemas Pydantic para la API de áreas de configuración del Helpdesk.
Solo permite editar metadata (label, icon, color, description, display_order).
No permite crear ni borrar áreas — las áreas DESARROLLO y SOPORTE son fijas.
"""
from pydantic import BaseModel, Field
from typing import Optional


class UpdateAreaRequest(BaseModel):
    """
    Edición de área: SOLO metadata visual.
    Campo inmutable excluido: code.
    """
    label: Optional[str] = Field(default=None, min_length=2, max_length=80)
    icon: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    display_order: Optional[int] = None


class ToggleAreaRequest(BaseModel):
    is_active: bool


class ReorderAreasRequest(BaseModel):
    order: list[dict]  # [{id: int, display_order: int}]
