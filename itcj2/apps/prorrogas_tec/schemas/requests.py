from pydantic import BaseModel
from typing import Optional, Literal


from enum import Enum

class RequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class RequestProBase(BaseModel):
    student_id: int
    program_id: int
    period_id: Optional[int] = None
    total_amount_id: int
    letter: Optional[str] = None
    payments_terms: int


class RequestProCreate(RequestProBase):
    pass

class RequestProUpdate(BaseModel):
    period_id: Optional[int] = None
    total_amount_id: Optional[int] = None
    letter: Optional[str] = None
    payments_terms: Optional[int] = None
    status: Optional[RequestStatus] = None

class RequestProOut(RequestProBase):
    id: int
    status: RequestStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True