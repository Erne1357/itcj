"""Config sub-router para maint — Field Template Builder y futuros módulos de config."""
from fastapi import APIRouter

from itcj2.apps.maint.api.config.field_templates import router as field_templates_router

config_router = APIRouter()
config_router.include_router(field_templates_router, prefix="/field-templates")
