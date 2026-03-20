from pydantic import BaseModel
from typing import Optional


class AssignTechnicianAreaRequest(BaseModel):
    """Registra el área de especialidad de un técnico (informativa, no restringe asignación)."""
    user_id: int
    area_code: str
    # Valores: TRANSPORT | GENERAL | ELECTRICAL | CARPENTRY | AC | GARDENING


class RemoveTechnicianAreaRequest(BaseModel):
    user_id: int
    area_code: Optional[str] = None
    # None → remueve todas las áreas del técnico
