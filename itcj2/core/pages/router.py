"""
Router de páginas del Core (prefix /itcj).

Cada sub-módulo implementa un grupo lógico equivalente a los Blueprints de Flask.
"""
from fastapi import APIRouter

from .auth import router as auth_router
from .config import router as config_router
from .dashboard import router as dashboard_router
from .mobile import router as mobile_router
from .profile import router as profile_router

core_pages_router = APIRouter(prefix="/itcj", tags=["core-pages"])

core_pages_router.include_router(auth_router)
core_pages_router.include_router(dashboard_router)
core_pages_router.include_router(profile_router)
core_pages_router.include_router(config_router)
core_pages_router.include_router(mobile_router)
