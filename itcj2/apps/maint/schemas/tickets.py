from decimal import Decimal
from pydantic import BaseModel, Field
from typing import Optional


class MaterialUseRequest(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    notes: Optional[str] = None


class CreateTicketRequest(BaseModel):
    category_id: int
    priority: str = "MEDIA"
    # Valores: BAJA | MEDIA | ALTA | URGENTE
    title: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=10)
    location: Optional[str] = Field(default=None, max_length=300)
    custom_fields: Optional[dict] = None
    # Campos del field_template de la categoría seleccionada


class UpdateTicketRequest(BaseModel):
    """Edición antes de que el ticket sea asignado."""
    category_id: Optional[int] = None
    priority: Optional[str] = None
    title: Optional[str] = Field(default=None, min_length=5, max_length=200)
    description: Optional[str] = Field(default=None, min_length=10)
    location: Optional[str] = Field(default=None, max_length=300)
    custom_fields: Optional[dict] = None


class ResolveTicketRequest(BaseModel):
    success: bool
    # True → RESOLVED_SUCCESS, False → RESOLVED_FAILED
    maintenance_type: str
    # PREVENTIVO | CORRECTIVO
    service_origin: str
    # INTERNO | EXTERNO
    resolution_notes: str = Field(min_length=10)
    time_invested_minutes: int = Field(ge=1)
    observations: Optional[str] = None
    materials_used: Optional[list[MaterialUseRequest]] = None


class RateTicketRequest(BaseModel):
    rating_attention: int = Field(ge=1, le=5)
    rating_speed: int = Field(ge=1, le=5)
    rating_efficiency: bool
    comment: Optional[str] = None


class CancelTicketRequest(BaseModel):
    reason: Optional[str] = None
