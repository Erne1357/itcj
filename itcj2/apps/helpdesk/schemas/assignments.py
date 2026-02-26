from pydantic import BaseModel
from typing import Optional


class AssignTicketRequest(BaseModel):
    ticket_id: int
    assigned_to_user_id: Optional[int] = None
    assigned_to_team: Optional[str] = None
    reason: Optional[str] = None


class ReassignTicketRequest(BaseModel):
    assigned_to_user_id: Optional[int] = None
    assigned_to_team: Optional[str] = None
    reason: str = "Ticket reasignado"
