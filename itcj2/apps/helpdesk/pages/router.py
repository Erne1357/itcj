"""
Router principal de páginas HTML de Help-Desk.

Agrupa todos los sub-routers bajo el prefijo ``/help-desk``,
equivalente al blueprint ``helpdesk_pages_bp`` de Flask.
"""
from fastapi import APIRouter

from .admin import router as admin_router
from .department import router as department_router
from .inventory import router as inventory_router
from .landing import router as landing_router
from .secretary import router as secretary_router
from .technician import router as technician_router
from .user import router as user_router

helpdesk_pages_router = APIRouter(prefix="/help-desk", tags=["helpdesk-pages"])

helpdesk_pages_router.include_router(landing_router)
helpdesk_pages_router.include_router(user_router)
helpdesk_pages_router.include_router(secretary_router)
helpdesk_pages_router.include_router(technician_router)
helpdesk_pages_router.include_router(department_router)
helpdesk_pages_router.include_router(inventory_router)
helpdesk_pages_router.include_router(admin_router)
