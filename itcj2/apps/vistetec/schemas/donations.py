"""Schemas Pydantic para donaciones de VisteTec."""
from typing import Optional
from pydantic import BaseModel


class GarmentDataBody(BaseModel):
    name: str
    category: str
    condition: str
    description: Optional[str] = None
    gender: Optional[str] = None
    size: Optional[str] = None
    brand: Optional[str] = None
    color: Optional[str] = None
    material: Optional[str] = None


class GarmentDonationBody(BaseModel):
    """Donación de prenda: puede ser una existente (garment_id) o nueva (garment)."""
    garment_id: Optional[int] = None
    garment: Optional[GarmentDataBody] = None
    donor_id: Optional[int] = None
    donor_name: Optional[str] = None
    notes: Optional[str] = None


class PantryDonationBody(BaseModel):
    pantry_item_id: int
    quantity: int = 1
    donor_id: Optional[int] = None
    donor_name: Optional[str] = None
    campaign_id: Optional[int] = None
    notes: Optional[str] = None
