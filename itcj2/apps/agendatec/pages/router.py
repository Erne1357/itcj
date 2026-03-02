"""
Router principal de páginas HTML de AgendaTec.

Agrupa todos los sub-routers bajo el prefijo ``/agendatec``,
equivalente al blueprint ``agendatec_pages_bp`` de Flask.
"""
from fastapi import APIRouter

from .admin import router as admin_router
from .coord import router as coord_router
from .landing import router as landing_router
from .social import router as social_router
from .student import router as student_router
from .surveys import router as surveys_router

agendatec_pages_router = APIRouter(prefix="/agendatec", tags=["agendatec-pages"])

agendatec_pages_router.include_router(landing_router)
agendatec_pages_router.include_router(student_router)
agendatec_pages_router.include_router(coord_router)
agendatec_pages_router.include_router(admin_router)
agendatec_pages_router.include_router(social_router)
agendatec_pages_router.include_router(surveys_router)
