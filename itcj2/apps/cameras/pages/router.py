"""Router principal de páginas HTML de Cámaras (prefijo /cameras)."""
from fastapi import APIRouter

from .viewer import router as viewer_router

cameras_pages_router = APIRouter(prefix="/cameras", tags=["cameras-pages"])
cameras_pages_router.include_router(viewer_router)
