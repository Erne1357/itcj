"""Schemas Pydantic para time slots de VisteTec."""
from typing import Optional
from pydantic import BaseModel, Field


class CreateScheduleBody(BaseModel):
    start_date: str
    end_date: str
    weekdays: list[int]
    start_time: str
    end_time: str
    slot_duration_minutes: int = Field(..., ge=1)
    max_students_per_slot: int = Field(1, ge=1)
    location_id: Optional[int] = None


class UpdateSlotBody(BaseModel):
    date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    max_students_per_slot: Optional[int] = None
    location_id: Optional[int] = None
