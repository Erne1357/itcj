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
from .surveys_admin import router as surveys_admin_router
from .survey_reviews_admin import router as survey_reviews_admin_router
from .handoff_admin import router as handoff_admin_router
from .access_admin import router as access_admin_router
from .library_admin import router as library_admin_router
from .cashier_admin import router as cashier_admin_router
from .certificates_admin import router as certificates_admin_router
from .mail_admin import router as mail_admin_router
from .audit_admin import router as audit_admin_router
from .reports_admin import router as reports_admin_router
from .titulacion_admin import router as titulacion_admin_router
from .titulacion_anexo import router as titulacion_anexo_router

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
titulatec_pages_router.include_router(surveys_admin_router)
titulatec_pages_router.include_router(survey_reviews_admin_router)
titulatec_pages_router.include_router(handoff_admin_router)
titulatec_pages_router.include_router(access_admin_router)
titulatec_pages_router.include_router(library_admin_router)
titulatec_pages_router.include_router(cashier_admin_router)
titulatec_pages_router.include_router(certificates_admin_router)
titulatec_pages_router.include_router(mail_admin_router)
titulatec_pages_router.include_router(audit_admin_router)
titulatec_pages_router.include_router(reports_admin_router)
# Pestaña Titulación (spec 2026-10-21 fase 3 §8): bandeja del Formato B.
# La vista «Anexo III» (fase 6, spec 2026-10-22 §9.2) va ANTES: ninguna ruta del
# prefijo `/admin/titulacion` debe poder capturar `anexo`.
titulatec_pages_router.include_router(titulacion_anexo_router)
titulatec_pages_router.include_router(titulacion_admin_router)
# Pestaña Docentes (spec 2026-10-21 fase 4 §8): catálogo por departamento.
from .docentes_admin import router as docentes_admin_router  # noqa: E402
titulatec_pages_router.include_router(docentes_admin_router)
# Pestaña Carreras por departamento (spec 2026-10-21 fase 4 §13): mapeo y oficio.
from .carreras_admin import router as carreras_admin_router  # noqa: E402
titulatec_pages_router.include_router(carreras_admin_router)
# Pestaña Días inhábiles (spec 2026-10-22 fase 5 §9.1): calendario de toda la app.
from .dias_inhabiles_admin import router as dias_inhabiles_admin_router  # noqa: E402
titulatec_pages_router.include_router(dias_inhabiles_admin_router)
# Pestaña Sinodales (spec 2026-10-21 fase 4 §9 y §12): bandeja, asignar,
# sustituir y el oficio en PDF.
from .sinodales_admin import router as sinodales_admin_router  # noqa: E402
titulatec_pages_router.include_router(sinodales_admin_router)
# Pestaña «Mis revisiones» (spec 2026-10-22 fase 5 §8.2): la bandeja del docente
# sinodal y la conversación de revisión de cada proceso.
from .revisiones_admin import router as revisiones_admin_router  # noqa: E402
titulatec_pages_router.include_router(revisiones_admin_router)
