"""Cameras app — router de API (v2). Vacío: la app es pages-only (HTMX)."""
from fastapi import APIRouter

cameras_router = APIRouter(prefix="/api/cameras/v2", tags=["cameras"])
