"""Credencial app: router de API (v2). Las rutas llegan en tareas posteriores."""
from fastapi import APIRouter

credencial_router = APIRouter(prefix="/api/credencial/v2", tags=["credencial"])
