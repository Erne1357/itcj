"""Router principal de paginas HTML de Credencial (prefijo /credencial)."""
from fastapi import APIRouter

from itcj2.apps.credencial.pages.admin import page_router as admin_page_router
from itcj2.apps.credencial.pages.admin import router as admin_router
from itcj2.apps.credencial.pages.public import router as public_router
from itcj2.apps.credencial.pages.student import router as student_router

credencial_pages_router = APIRouter(prefix="/credencial", tags=["credencial-pages"])
credencial_pages_router.include_router(public_router)
credencial_pages_router.include_router(student_router)
credencial_pages_router.include_router(admin_page_router)
credencial_pages_router.include_router(admin_router)
