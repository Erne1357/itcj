from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field


class StockEntryCreate(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    purchase_date: date
    purchase_folio: str = Field(min_length=1, max_length=100)
    unit_cost: Decimal = Field(gt=0)
    supplier: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = None


class StockEntryVoidRequest(BaseModel):
    reason: str = Field(min_length=5)


class StockEntryOut(BaseModel):
    id: int
    product_id: int
    quantity_original: Decimal
    quantity_remaining: Decimal
    purchase_date: date
    purchase_folio: str
    unit_cost: Decimal
    supplier: Optional[str]
    notes: Optional[str]
    is_exhausted: bool
    voided: bool
    voided_at: Optional[datetime]
    void_reason: Optional[str]
    registered_at: datetime

    model_config = {"from_attributes": True}


class AdjustRequest(BaseModel):
    """Ajuste manual de stock (corrección positiva o negativa)."""
    product_id: int
    quantity: Decimal = Field(gt=0)
    adjust_type: Literal["IN", "OUT"]
    notes: str = Field(min_length=5)
    justification: str = Field(min_length=10)
