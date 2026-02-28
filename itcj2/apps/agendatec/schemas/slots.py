from pydantic import BaseModel


class HoldSlotBody(BaseModel):
    slot_id: int


class ReleaseSlotBody(BaseModel):
    slot_id: int
