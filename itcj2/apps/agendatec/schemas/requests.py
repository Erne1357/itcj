from pydantic import BaseModel
from typing import Optional, Literal


class CreateRequestBody(BaseModel):
    type: Literal["DROP", "APPOINTMENT"]
    program_id: int
    slot_id: Optional[int] = None
    description: Optional[str] = None
