"""Maint app — router assembly (v1)."""
from fastapi import APIRouter

from itcj2.apps.maint.api.tickets import router as tickets_router
from itcj2.apps.maint.api.assignments import router as assignments_router
from itcj2.apps.maint.api.comments import router as comments_router
from itcj2.apps.maint.api.categories import router as categories_router
from itcj2.apps.maint.api.technicians import router as technicians_router

maint_router = APIRouter(prefix="/api/maint/v2", tags=["maint"])

maint_router.include_router(tickets_router, prefix="/tickets")
maint_router.include_router(assignments_router, prefix="/tickets")
maint_router.include_router(comments_router, prefix="/tickets")
maint_router.include_router(categories_router, prefix="/categories")
maint_router.include_router(technicians_router, prefix="/technicians")
