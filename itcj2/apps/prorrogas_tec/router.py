# """Prorrogas_tec app — router assembly (v2)."""
from fastapi import APIRouter

from itcj2.apps.prorrogas_tec.api.invitations import router as invitations
from itcj2.apps.prorrogas_tec.api.programs import router as programs
from itcj2.apps.prorrogas_tec.api.student import router as student
from itcj2.apps.prorrogas_tec.api.templates import router as templates_router


prorrogas_tec_router = APIRouter(prefix="/api/prorrogas/v2", tags=["prorrogas_tec"])

prorrogas_tec_router.include_router(programs, prefix="/programs")
prorrogas_tec_router.include_router(templates_router, prefix="/templates")
prorrogas_tec_router.include_router(invitations, prefix="/invitaciones")
prorrogas_tec_router.include_router(student, prefix="/estudiante")
