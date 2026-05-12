"""Sub-módulo de configuración del Helpdesk — ensamblado de routers."""
from fastapi import APIRouter

from .priorities import router as priorities_router
from .statuses import router as statuses_router
from .transitions import router as transitions_router
from .audit import router as audit_router
from .areas import router as areas_router
from .notifications import router as notifications_router

config_router = APIRouter(prefix="/config", tags=["helpdesk-config"])
config_router.include_router(priorities_router, prefix="/priorities")
config_router.include_router(statuses_router, prefix="/statuses")
config_router.include_router(transitions_router, prefix="/transitions")
config_router.include_router(audit_router, prefix="/audit")
config_router.include_router(areas_router, prefix="/areas")
config_router.include_router(notifications_router, prefix="/notifications")
