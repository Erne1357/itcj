"""Config sub-router para maint — Field Templates, Prioridades, Catálogos y Auditoría."""
from fastapi import APIRouter

from itcj2.apps.maint.api.config.field_templates import router as field_templates_router
from itcj2.apps.maint.api.config.priorities import router as priorities_router
from itcj2.apps.maint.api.config.maint_types import router as maint_types_router
from itcj2.apps.maint.api.config.service_origins import router as service_origins_router
from itcj2.apps.maint.api.config.audit import router as audit_router

config_router = APIRouter()
config_router.include_router(field_templates_router, prefix="/field-templates")
config_router.include_router(priorities_router, prefix="/priorities")
config_router.include_router(maint_types_router, prefix="/maint-types")
config_router.include_router(service_origins_router, prefix="/service-origins")
config_router.include_router(audit_router, prefix="/audit")
