from decimal import Decimal

from pydantic import BaseModel


class LowStockProductOut(BaseModel):
    id: int
    code: str
    name: str
    department_code: str
    total_stock: Decimal
    restock_point: Decimal
    unit_of_measure: str


class WarehouseDashboardOut(BaseModel):
    """Stats generales del almacén, filtrados por dept del usuario."""
    total_products: int
    total_categories: int
    low_stock_count: int
    total_stock_value: Decimal
    low_stock_products: list[LowStockProductOut]
    movements_today: int
    entries_this_month: int
