"""AgendaTec app — router assembly (v2)."""
from fastapi import APIRouter

# Endpoints de estudiante
from itcj2.apps.agendatec.api.requests import router as requests_router
from itcj2.apps.agendatec.api.slots import router as slots_router
from itcj2.apps.agendatec.api.availability import router as availability_router
from itcj2.apps.agendatec.api.programs import router as programs_router
from itcj2.apps.agendatec.api.notifications import router as notifications_router
from itcj2.apps.agendatec.api.periods import router as periods_router
from itcj2.apps.agendatec.api.social import router as social_router

# Endpoints de administrador
from itcj2.apps.agendatec.api.admin.requests import router as admin_requests_router
from itcj2.apps.agendatec.api.admin.users import router as admin_users_router
from itcj2.apps.agendatec.api.admin.stats import router as admin_stats_router
from itcj2.apps.agendatec.api.admin.reports import router as admin_reports_router
from itcj2.apps.agendatec.api.admin.surveys import router as admin_surveys_router

# Endpoints de coordinador
from itcj2.apps.agendatec.api.coord.appointments import router as coord_appointments_router
from itcj2.apps.agendatec.api.coord.dashboard import router as coord_dashboard_router
from itcj2.apps.agendatec.api.coord.day_config import router as coord_day_config_router
from itcj2.apps.agendatec.api.coord.drops import router as coord_drops_router
from itcj2.apps.agendatec.api.coord.password import router as coord_password_router

agendatec_router = APIRouter(prefix="/api/agendatec/v2", tags=["agendatec"])

# ── Estudiante ────────────────────────────────────────────────────────────────
agendatec_router.include_router(requests_router, prefix="/requests")
agendatec_router.include_router(slots_router, prefix="/slots")
agendatec_router.include_router(availability_router, prefix="/availability")
agendatec_router.include_router(programs_router, prefix="/programs")
agendatec_router.include_router(notifications_router, prefix="/notifications")
agendatec_router.include_router(periods_router, prefix="/periods")
agendatec_router.include_router(social_router, prefix="/social")

# ── Administrador ─────────────────────────────────────────────────────────────
agendatec_router.include_router(admin_requests_router, prefix="/admin")
agendatec_router.include_router(admin_users_router, prefix="/admin")
agendatec_router.include_router(admin_stats_router, prefix="/admin")
agendatec_router.include_router(admin_reports_router, prefix="/admin")
agendatec_router.include_router(admin_surveys_router, prefix="/admin")

# ── Coordinador ───────────────────────────────────────────────────────────────
agendatec_router.include_router(coord_appointments_router, prefix="/coord")
agendatec_router.include_router(coord_dashboard_router, prefix="/coord")
agendatec_router.include_router(coord_day_config_router, prefix="/coord")
agendatec_router.include_router(coord_drops_router, prefix="/coord")
agendatec_router.include_router(coord_password_router, prefix="/coord")
