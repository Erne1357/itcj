from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class WarehouseProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: Optional[str] = None
    subcategory_id: int
    department_code: str = Field(max_length=50)
    unit_of_measure: str = Field(max_length=30)
    icon: str = Field(default="bi-box", max_length=50)
    restock_lead_time_days: int = Field(default=7, ge=0)


class WarehouseProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=150)
    description: Optional[str] = None
    subcategory_id: Optional[int] = None
    unit_of_measure: Optional[str] = Field(default=None, max_length=30)
    icon: Optional[str] = Field(default=None, max_length=50)
    restock_lead_time_days: Optional[int] = Field(default=None, ge=0)


class RestockOverrideRequest(BaseModel):
    """Setear o quitar el override manual del punto de restock.
    Enviar None para remover el override y volver al cálculo automático.
    """
    restock_point_override: Optional[Decimal] = Field(default=None, ge=0)


class WarehouseProductOut(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str]
    subcategory_id: int
    department_code: str
    unit_of_measure: str
    icon: str
    is_active: bool
    restock_point_auto: Decimal
    restock_point_override: Optional[Decimal]
    restock_lead_time_days: int
    last_restock_calc_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WarehouseProductWithStockOut(WarehouseProductOut):
    """Producto enriquecido con datos de stock calculados en el service."""
    total_stock: Decimal
    is_below_restock: bool
    restock_point: Decimal
    total_stock_value: Decimal


class WarehouseProductAvailableOut(BaseModel):
    """Respuesta ligera para autocomplete en formularios de tickets."""
    id: int
    code: str
    name: str
    unit_of_measure: str
    total_stock: Decimal
    department_code: str

    model_config = {"from_attributes": True}
