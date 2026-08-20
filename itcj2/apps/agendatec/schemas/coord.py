from pydantic import BaseModel, Field
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
    # Cota tambien aqui, no solo en el endpoint: sin ella un 0 o un negativo
    # llega al generador de rejilla y produce un bucle infinito.
    slot_minutes: int = Field(default=10, ge=5, le=60)
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
