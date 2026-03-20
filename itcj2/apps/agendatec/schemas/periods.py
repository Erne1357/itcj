from pydantic import BaseModel
from typing import Optional, List


class CreatePeriodBody(BaseModel):
    code: str
    name: str
    start_date: str
    end_date: str
    student_admission_start: str
    student_admission_deadline: str
    status: str = "INACTIVE"
    max_cancellations_per_student: int = 2
    allow_drop_requests: bool = True
    allow_appointment_requests: bool = True


class UpdatePeriodBody(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    student_admission_start: Optional[str] = None
    student_admission_deadline: Optional[str] = None
    max_cancellations_per_student: Optional[int] = None
    allow_drop_requests: Optional[bool] = None
    allow_appointment_requests: Optional[bool] = None
    status: Optional[str] = None


class SetEnabledDaysBody(BaseModel):
    days: List[str]
