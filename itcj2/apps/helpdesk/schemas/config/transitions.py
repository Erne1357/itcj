"""
Schemas Pydantic para el CRUD de transiciones de estado del Helpdesk.
"""
from pydantic import BaseModel
from typing import Optional


class CreateTransitionRequest(BaseModel):
    from_status_id: int
    to_status_id: int
    required_perm: Optional[str] = None
    required_fields: Optional[list[str]] = None


class UpdateTransitionRequest(BaseModel):
    required_perm: Optional[str] = None
    required_fields: Optional[list[str]] = None
    is_active: Optional[bool] = None


class BulkSetTransitionsRequest(BaseModel):
    """
    Para que la matriz pueda enviar todo el set en un solo PUT.
    Cada elemento puede tener: from_status_id, to_status_id,
    required_perm (opcional), required_fields (opcional), is_active (opcional, default True).
    Pares no presentes en el payload pero activos en BD serán desactivados.
    """
    transitions: list[dict]
