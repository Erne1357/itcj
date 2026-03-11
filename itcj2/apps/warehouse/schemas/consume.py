from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field

# Apps que pueden consumir del almacén
SourceApp = Literal["helpdesk", "maint"]


class ConsumeRequest(BaseModel):
    """
    Solicitud de consumo FIFO desde una app consumidora.
    Llamado internamente desde ticket_service de helpdesk/maint.
    """
    product_id: int
    quantity: Decimal = Field(gt=0)
    source_app: SourceApp
    source_ticket_id: int
    notes: Optional[str] = None


class MaterialUseRequest(BaseModel):
    """
    Referencia a un material dentro del body de resolución de ticket.
    Usado por helpdesk y maint al resolver un ticket con materiales.
    """
    product_id: int
    quantity: Decimal = Field(gt=0)
    notes: Optional[str] = None


class WarehouseTicketMaterialOut(BaseModel):
    id: int
    source_app: str
    source_ticket_id: int
    product_id: int
    quantity_used: Decimal
    added_at: datetime
    notes: Optional[str]

    model_config = {"from_attributes": True}


class WarehouseTicketMaterialDetailOut(WarehouseTicketMaterialOut):
    """Vista enriquecida con nombre y unidad del producto (para el detalle del ticket)."""
    product_code: str
    product_name: str
    unit_of_measure: str
