from pydantic import BaseModel, Field
from typing import Optional


class ResolveTicketRequest(BaseModel):
    success: bool
    resolution_notes: str
    time_invested_minutes: int
    maintenance_type: Optional[str] = None
    service_origin: Optional[str] = None
    observations: Optional[str] = None


class RateTicketRequest(BaseModel):
    rating_attention: int = Field(ge=1, le=5)
    rating_speed: int = Field(ge=1, le=5)
    rating_efficiency: bool
    comment: Optional[str] = None


class CancelTicketRequest(BaseModel):
    reason: Optional[str] = None


class UpdateTicketRequest(BaseModel):
    area: Optional[str] = None
    category_id: Optional[int] = None
    priority: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None


class AddCollaboratorRequest(BaseModel):
    user_id: int
    collaboration_role: Optional[str] = None
    time_invested_minutes: Optional[int] = None
    notes: Optional[str] = None


class AddCollaboratorsBatchRequest(BaseModel):
    collaborators: list[AddCollaboratorRequest]


class UpdateCollaboratorRequest(BaseModel):
    time_invested_minutes: Optional[int] = None
    notes: Optional[str] = None


class AddEquipmentRequest(BaseModel):
    item_ids: list[int]


class ReplaceEquipmentRequest(BaseModel):
    item_ids: list[int]
