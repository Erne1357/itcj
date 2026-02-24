from fastapi import APIRouter

core_router = APIRouter(prefix="/api/core/v2", tags=["core"])

# Auth: login, logout, me
from .api.auth import router as auth_router
core_router.include_router(auth_router)

# User: perfil, contraseña, actividad, notificaciones del usuario
from .api.users import router as users_router
core_router.include_router(users_router)

# Notifications: listado, marcar leídas, eliminar
from .api.notifications import router as notifications_router
core_router.include_router(notifications_router)
