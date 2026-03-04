"""VisteTec app — router assembly (v2)."""
from fastapi import APIRouter

from itcj2.apps.vistetec.api.appointments import router as appointments_router
from itcj2.apps.vistetec.api.catalog import router as catalog_router
from itcj2.apps.vistetec.api.donations import router as donations_router
from itcj2.apps.vistetec.api.garments import router as garments_router
from itcj2.apps.vistetec.api.pantry import router as pantry_router
from itcj2.apps.vistetec.api.reports import router as reports_router
from itcj2.apps.vistetec.api.time_slots import router as slots_router

vistetec_router = APIRouter(prefix="/api/vistetec/v2", tags=["vistetec"])

vistetec_router.include_router(appointments_router, prefix="/appointments")
vistetec_router.include_router(catalog_router, prefix="/catalog")
vistetec_router.include_router(donations_router, prefix="/donations")
vistetec_router.include_router(garments_router, prefix="/garments")
vistetec_router.include_router(pantry_router, prefix="/pantry")
vistetec_router.include_router(reports_router, prefix="/reports")
vistetec_router.include_router(slots_router, prefix="/slots")
