"""Schemas Pydantic para citas de VisteTec."""
from typing import Optional
from pydantic import BaseModel


class CreateAppointmentBody(BaseModel):
    garment_id: int
    slot_id: int
    will_bring_donation: bool = False


class AttendanceBody(BaseModel):
    attended: bool


class CompleteAppointmentBody(BaseModel):
    outcome: str
    notes: Optional[str] = None
