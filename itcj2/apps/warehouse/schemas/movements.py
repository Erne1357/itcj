from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class MovementOut(BaseModel):
    id: int
    product_id: int
    entry_id: Optional[int]
    movement_type: str
    quantity: Decimal
    # Relación polimórfica con ticket (nullable si no viene de un ticket)
    source_app: Optional[str]
    source_ticket_id: Optional[int]
    performed_by_id: int
    performed_at: datetime
    notes: Optional[str]

    model_config = {"from_attributes": True}


class MovementDetailOut(MovementOut):
    """Vista enriquecida para el historial de movimientos en el panel."""
    product_code: str
    product_name: str
    performed_by_name: str
