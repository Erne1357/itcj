"""
Router principal de páginas HTML de Prorrogas.

Agrupa todos los sub-routers bajo el prefijo ``/prorrogas_tec``,
equivalente al blueprint ``agendatec_pages_bp`` de Flask.
"""
from fastapi import APIRouter

from .admin import router as admin_router
from .landing import router as landing_router
from .student import router as student_router

prorrogas_tec_pages_router = APIRouter(prefix="/prorrogas", tags=["prorrogas_tec-pages"])

prorrogas_tec_pages_router.include_router(admin_router)
prorrogas_tec_pages_router.include_router(landing_router)
prorrogas_tec_pages_router.include_router(student_router)