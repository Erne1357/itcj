# """Prorrogas_tec app — router assembly (v2)."""
from fastapi import APIRouter

# # Endpoints de estudiante
from itcj2.apps.prorrogas_tec.api.requests import router as requests_router2
from itcj2.apps.prorrogas_tec.api.student.requests import router as requests_router3
from itcj2.apps.prorrogas_tec.api.periods import router as periods_router2
from itcj2.apps.prorrogas_tec.api.programs import router as programs


prorrogas_tec_router = APIRouter(prefix="/api/prorrogas/v2", tags=["prorrogas_tec"])

prorrogas_tec_router.include_router(periods_router2, prefix="/periods")
prorrogas_tec_router.include_router(requests_router2, prefix="/request")
prorrogas_tec_router.include_router(requests_router3, prefix="/request2")
prorrogas_tec_router.include_router(programs, prefix="/programs")


