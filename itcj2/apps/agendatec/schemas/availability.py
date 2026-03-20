from pydantic import BaseModel
from typing import Optional, List


class CreateWindowBody(BaseModel):
    day: str
    start: str
    end: str
    slot_minutes: int = 10
    coordinator_id: Optional[int] = None


class GenerateSlotsBody(BaseModel):
    day: Optional[str] = None
    days: Optional[List[str]] = None
