"""Router principal de páginas HTML de Mantenimiento."""
from fastapi import APIRouter

from itcj2.apps.maint.pages.landing import router as landing_router
from itcj2.apps.maint.pages.tickets import router as tickets_router
from itcj2.apps.maint.pages.admin import router as admin_router

maint_pages_router = APIRouter(prefix="/mantenimiento", tags=["maint-pages"])

maint_pages_router.include_router(landing_router)
maint_pages_router.include_router(tickets_router)
maint_pages_router.include_router(admin_router)
