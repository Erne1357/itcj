"""Router principal de páginas HTML de TitulaTec.

Agrupa los sub-routers de páginas bajo el prefijo ``/titulatec``.
  - student/  → flujo del alumno (mobile-first)
  - admin/    → bandeja administrativa (desktop)
  - landing   → redirección por rol
"""
from fastapi import APIRouter

from .landing import router as landing_router
from .student import router as student_router
from .admin import router as admin_router
from .appointments import router as appointments_router
from .roles import router as roles_router
from .officers import router as officers_router

titulatec_pages_router = APIRouter(prefix="/titulatec", tags=["titulatec-pages"])

titulatec_pages_router.include_router(landing_router)
titulatec_pages_router.include_router(student_router)
titulatec_pages_router.include_router(admin_router)
titulatec_pages_router.include_router(appointments_router)
titulatec_pages_router.include_router(roles_router)
titulatec_pages_router.include_router(officers_router)
