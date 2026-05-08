"""Sub-módulo de configuración del Helpdesk — ensamblado de routers."""
from fastapi import APIRouter

from .priorities import router as priorities_router
from .audit import router as audit_router

config_router = APIRouter(prefix="/config", tags=["helpdesk-config"])
config_router.include_router(priorities_router, prefix="/priorities")
config_router.include_router(audit_router, prefix="/audit")
