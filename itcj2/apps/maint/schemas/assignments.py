from pydantic import BaseModel
from typing import Optional


class AssignTechnicianRequest(BaseModel):
    """Asigna uno o más técnicos a un ticket. Los técnicos se agregan acumulativamente."""
    user_ids: list[int]
    # Lista de IDs — permite asignación múltiple en un solo request
    notes: Optional[str] = None


class UnassignTechnicianRequest(BaseModel):
    """Remueve a un técnico activo del ticket."""
    user_id: int
    reason: Optional[str] = None
