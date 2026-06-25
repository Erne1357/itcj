"""Router principal de páginas HTML del Directorio (prefijo /directory)."""
from fastapi import APIRouter

from .directory import router as directory_pages_subrouter

directory_pages_router = APIRouter(prefix="/directory", tags=["directory-pages"])
directory_pages_router.include_router(directory_pages_subrouter)
