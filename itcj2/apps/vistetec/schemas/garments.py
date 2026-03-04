"""Schemas Pydantic para gestión de prendas de VisteTec."""
from typing import Optional
from pydantic import BaseModel


class GarmentCreateBody(BaseModel):
    name: str
    description: Optional[str] = None
    category: str
    gender: Optional[str] = None
    size: Optional[str] = None
    brand: Optional[str] = None
    color: Optional[str] = None
    material: Optional[str] = None
    condition: str
    donated_by_id: Optional[int] = None


class GarmentUpdateBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    gender: Optional[str] = None
    size: Optional[str] = None
    brand: Optional[str] = None
    color: Optional[str] = None
    material: Optional[str] = None
    condition: Optional[str] = None
