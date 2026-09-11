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
from .documents import router as documents_router
from .public import router as public_router
from .requests_admin import router as requests_admin_router

titulatec_pages_router = APIRouter(prefix="/titulatec", tags=["titulatec-pages"])

titulatec_pages_router.include_router(landing_router)
titulatec_pages_router.include_router(student_router)
titulatec_pages_router.include_router(admin_router)
titulatec_pages_router.include_router(appointments_router)
titulatec_pages_router.include_router(roles_router)
titulatec_pages_router.include_router(officers_router)
titulatec_pages_router.include_router(documents_router)
# El ÚNICO sub-router sin `require_page_*`: sus rutas son públicas por omitir la
# dependencia (no hay allowlist en este repo). Ver `public.py`.
titulatec_pages_router.include_router(public_router)
titulatec_pages_router.include_router(requests_admin_router)
