"""Adhoc (Calidad) — router de API (v2).

Los sub-routers de cada dominio (documentos, incidencias, programas, tareas,
indicadores, panel, reportes) se irán incluyendo aquí en F4, con el prefijo
puesto por el PADRE:

    adhoc_router.include_router(documents_router, prefix="/documents")

El hijo declara solo ``APIRouter(tags=["adhoc-documents"])``.
"""
from fastapi import APIRouter

adhoc_router = APIRouter(prefix="/api/adhoc/v2", tags=["adhoc"])
# TODO(F4): incluir aquí los sub-routers de itcj2/apps/adhoc/api/.
