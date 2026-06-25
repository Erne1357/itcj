"""Directory app — router de API (v2). Vacío en v1: la app es pages-only."""
from fastapi import APIRouter

directory_router = APIRouter(prefix="/api/directory/v2", tags=["directory"])
# Sin sub-routers en v1 (toda la lógica vive en pages/).
