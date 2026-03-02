"""
Router principal de páginas HTML de VisteTec.

Agrupa todos los sub-routers bajo el prefijo ``/vistetec``,
equivalente al blueprint ``vistetec_pages_bp`` de Flask.
"""
from fastapi import APIRouter

from .admin import router as admin_router
from .landing import router as landing_router
from .student import router as student_router
from .volunteer import router as volunteer_router

vistetec_pages_router = APIRouter(prefix="/vistetec", tags=["vistetec-pages"])

vistetec_pages_router.include_router(landing_router)
vistetec_pages_router.include_router(student_router)
vistetec_pages_router.include_router(volunteer_router)
vistetec_pages_router.include_router(admin_router)
