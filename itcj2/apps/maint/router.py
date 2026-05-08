"""Maint app — router assembly (v1)."""
from fastapi import APIRouter

from itcj2.apps.maint.api.tickets import router as tickets_router
from itcj2.apps.maint.api.assignments import router as assignments_router
from itcj2.apps.maint.api.comments import router as comments_router
from itcj2.apps.maint.api.categories import router as categories_router
from itcj2.apps.maint.api.technicians import router as technicians_router
from itcj2.apps.maint.api.warehouse_proxy import router as warehouse_router
from itcj2.apps.maint.api.attachments import router as attachments_router
from itcj2.apps.maint.api.dashboard import router as dashboard_router
from itcj2.apps.maint.api.admin import router as admin_router
from itcj2.apps.maint.api.reports import router as reports_router
from itcj2.apps.maint.api.stats import router as stats_router
from itcj2.apps.maint.api.analysis import router as analysis_router

maint_router = APIRouter(prefix="/api/maint/v2", tags=["maint"])

maint_router.include_router(dashboard_router, prefix="/dashboard")
maint_router.include_router(tickets_router, prefix="/tickets")
maint_router.include_router(assignments_router, prefix="/tickets")
maint_router.include_router(comments_router, prefix="/tickets")
maint_router.include_router(categories_router, prefix="/categories")
maint_router.include_router(technicians_router, prefix="/technicians")
maint_router.include_router(warehouse_router, prefix="/warehouse")
maint_router.include_router(attachments_router)
maint_router.include_router(admin_router, prefix="/admin")
maint_router.include_router(reports_router, prefix="/reports")
maint_router.include_router(stats_router, prefix="/stats")
maint_router.include_router(analysis_router, prefix="/analysis")
