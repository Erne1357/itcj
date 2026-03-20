from pydantic import BaseModel
from typing import Optional, List


class ChangeRequestStatusBody(BaseModel):
    status: str
    reason: Optional[str] = ""


class AdminCreateRequestBody(BaseModel):
    student_id: int
    type: str
    program_id: int
    description: str
    slot_id: Optional[int] = None


class CreateCoordinatorBody(BaseModel):
    user_id: Optional[int] = None
    name: Optional[str] = None
    email: Optional[str] = None
    username: Optional[str] = None
    program_ids: List[int] = []


class UpdateCoordinatorBody(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    program_ids: Optional[List[int]] = None
