"""TitulaTec app — router assembly (v2).

Agrupa los sub-routers de API bajo ``/api/titulatec/v2``.
Cada recurso (procesos, fases, documentos, formato-b, sinodales, chat,
convocatorias, citas, actos) registra aquí su sub-router conforme se implementa.
"""
from fastapi import APIRouter

titulatec_router = APIRouter(prefix="/api/titulatec/v2", tags=["titulatec"])

# ── Sub-routers ───────────────────────────────────────────────────────────────
# Se irán incluyendo conforme se construyan los módulos. Ejemplo:
# from itcj2.apps.titulatec.api.processes import router as processes_router
# titulatec_router.include_router(processes_router, prefix="/processes")
