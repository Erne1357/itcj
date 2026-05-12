"""
Schemas Pydantic para la API de estados de configuración del Helpdesk.
Solo permite editar metadata de presentación (label, color, etc.).
No permite crear ni borrar estados — eso es responsabilidad del equipo de desarrollo.
"""
from pydantic import BaseModel, Field
from typing import Optional


class UpdateStatusRequest(BaseModel):
    """
    Edición de estado: SOLO metadata visual.
    Campos inmutables excluidos: code, progress_pct, stage, is_open, is_resolved, is_terminal.
    """
    label: Optional[str] = Field(default=None, min_length=2, max_length=60)
    color: Optional[str] = None
    badge_class: Optional[str] = None
    icon: Optional[str] = None
    display_order: Optional[int] = None


class ToggleStatusRequest(BaseModel):
    is_active: bool


class ReorderStatusesRequest(BaseModel):
    order: list[dict]  # [{id: int, display_order: int}]
