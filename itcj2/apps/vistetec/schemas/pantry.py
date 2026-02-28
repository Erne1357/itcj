"""Schemas Pydantic para despensa de VisteTec."""
from typing import Optional
from pydantic import BaseModel


class PantryItemBody(BaseModel):
    name: str
    category: Optional[str] = None
    unit: Optional[str] = None
    description: Optional[str] = None


class StockMovementBody(BaseModel):
    item_id: int
    quantity: int
    notes: Optional[str] = None


class PantryCampaignBody(BaseModel):
    name: str
    description: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    goal: Optional[int] = None
