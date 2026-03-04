from pydantic import BaseModel
from typing import Optional


class UpdateAppointmentBody(BaseModel):
    status: str


class UpdateRequestStatusBody(BaseModel):
    status: str
    coordinator_comment: Optional[str] = None


class SetDayConfigBody(BaseModel):
    day: str
    start: str
    end: str
    slot_minutes: int = 10


class DeleteDayRangeBody(BaseModel):
    day: str
    start: str
    end: str


class ChangePasswordBody(BaseModel):
    new_password: str
