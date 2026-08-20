from pydantic import BaseModel
from typing import List, Optional


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
    # None o [] => todas las carreras del coordinador. El default preserva el
    # comportamiento anterior para quien no use el scope.
    programs: Optional[List[int]] = None


class PreviewDayConfigBody(SetDayConfigBody):
    """Mismo cuerpo que SetDayConfigBody; endpoint distinto, sin efectos."""


class DeleteDayRangeBody(BaseModel):
    day: str
    start: str
    end: str


class ChangePasswordBody(BaseModel):
    new_password: str
