from fastapi import APIRouter

core_router = APIRouter(prefix="/api/core/v2", tags=["core"])

# Auth: login, logout, me
from .api.auth import router as auth_router
core_router.include_router(auth_router)

# User: perfil, contraseña, actividad, notificaciones del usuario
from .api.users import router as users_router
core_router.include_router(users_router)

# Users Admin: lista, crear, actualizar, reset (gestión administrativa)
from .api.users_admin import router as users_admin_router
core_router.include_router(users_admin_router)

# Notifications: listado, marcar leídas, eliminar
from .api.notifications import router as notifications_router
core_router.include_router(notifications_router)

# Authorization: apps, roles, permisos, asignación usuario/puesto
from .api.authz import router as authz_router
core_router.include_router(authz_router, prefix="/authz")

# Departments: jerarquía, CRUD, usuarios por depto
from .api.departments import router as departments_router
core_router.include_router(departments_router, prefix="/departments")

# Positions: CRUD, asignaciones, permisos por puesto
from .api.positions import router as positions_router
core_router.include_router(positions_router, prefix="/positions")

# Themes: temas visuales del sistema
from .api.themes import router as themes_router
core_router.include_router(themes_router, prefix="/themes")

# Deploy: notificaciones de archivos estáticos
from .api.deploy import router as deploy_router
core_router.include_router(deploy_router, prefix="/deploy")

# Mobile: apps y tipo de usuario para el dashboard móvil
from .api.mobile import router as mobile_router
core_router.include_router(mobile_router, prefix="/mobile")

# Tasks: gestión de tareas Celery (catálogo, schedules, historial)
from .api.tasks import router as tasks_router
core_router.include_router(tasks_router, prefix="/tasks")
