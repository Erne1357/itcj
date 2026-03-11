"""Warehouse app — router assembly."""
from fastapi import APIRouter

from itcj2.apps.warehouse.api.categories import router as categories_router
from itcj2.apps.warehouse.api.products import router as products_router
from itcj2.apps.warehouse.api.entries import router as entries_router
from itcj2.apps.warehouse.api.movements import router as movements_router
from itcj2.apps.warehouse.api.consume import router as consume_router
from itcj2.apps.warehouse.api.dashboard import router as dashboard_router
from itcj2.apps.warehouse.api.reports import router as reports_router

warehouse_router = APIRouter(prefix="/api/warehouse/v2", tags=["warehouse"])

warehouse_router.include_router(categories_router)
warehouse_router.include_router(products_router)
warehouse_router.include_router(entries_router)
warehouse_router.include_router(movements_router)
warehouse_router.include_router(consume_router)
warehouse_router.include_router(dashboard_router)
warehouse_router.include_router(reports_router)
