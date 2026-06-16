"""Schemas Pydantic para el módulo de coordinadores de mantenimiento."""
from pydantic import BaseModel
from typing import Optional


class SetCoordinatorAreasRequest(BaseModel):
    """Reemplaza el set de áreas de un coordinador de área."""
    area_codes: list[str]


class CoordinatorAreaInfo(BaseModel):
    """Información de un coordinador devuelta en listados."""
    user_id: int
    name: str
    areas: list[str]
    is_general: bool
