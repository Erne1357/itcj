"""Inventory sub-module router assembly."""
from fastapi import APIRouter

from .items import router as items_router
from .assignments import router as assignments_router
from .categories import router as categories_router
from .dashboard import router as dashboard_router
from .groups import router as groups_router
from .history import router as history_router
from .pending import router as pending_router
from .selection import router as selection_router
from .stats import router as stats_router
from .bulk import router as bulk_router
from .reports import router as reports_router
from .verification import router as verification_router
from .bulk_transfer import router as bulk_transfer_router
from .retirement_requests import router as retirement_router

inventory_router = APIRouter(tags=["helpdesk-inventory"])

inventory_router.include_router(items_router, prefix="/items")
inventory_router.include_router(assignments_router, prefix="/assignments")
inventory_router.include_router(categories_router, prefix="/categories")
inventory_router.include_router(dashboard_router, prefix="/dashboard")
inventory_router.include_router(groups_router, prefix="/groups")
inventory_router.include_router(history_router, prefix="/history")
inventory_router.include_router(pending_router, prefix="/pending")
inventory_router.include_router(selection_router, prefix="/selection")
inventory_router.include_router(stats_router, prefix="/stats")
inventory_router.include_router(bulk_router, prefix="/bulk")
inventory_router.include_router(reports_router, prefix="/reports")
inventory_router.include_router(verification_router, prefix="/verification")
inventory_router.include_router(bulk_transfer_router, prefix="/items")
inventory_router.include_router(retirement_router, prefix="/retirement-requests")
