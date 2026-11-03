"""Router principal de paginas HTML de Credencial (prefijo /credencial). Las rutas llegan despues."""
from fastapi import APIRouter

credencial_pages_router = APIRouter(prefix="/credencial", tags=["credencial-pages"])
