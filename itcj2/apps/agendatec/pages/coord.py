"""
Páginas de coordinadores para AgendaTec.
Equivalente a itcj/apps/agendatec/routes/pages/coord.py.

Rutas:
  GET /agendatec/coord/              → Redirige a /coord/home
  GET /agendatec/coord/home          → Dashboard del coordinador
  GET /agendatec/coord/appointments  → Citas del día
  GET /agendatec/coord/drops         → Bajas
  GET /agendatec/coord/slots         → Configuración de horario
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from itcj2.apps.agendatec.pages.nav import render_agendatec
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.agendatec.pages.coord")

router = APIRouter(prefix="/coord", tags=["agendatec-pages-coord"])


@router.get("", include_in_schema=False)
@router.get("/", name="agendatec.pages.coord.index")
async def coord_index(
    request: Request,
    user: dict = Depends(require_page_app("agendatec", perms=["agendatec.coord_dashboard.page.view"])),
):
    """Redirige al home del coordinador."""
    return RedirectResponse("/agendatec/coord/home", status_code=302)


@router.get("/home", name="agendatec.pages.coord.home")
async def coord_home_page(
    request: Request,
    user: dict = Depends(require_page_app("agendatec", perms=["agendatec.coord_dashboard.page.view"])),
):
    """Dashboard principal del coordinador."""
    return render_agendatec(request, "agendatec/coord/home.html", {
        "title": "Coordinador - Dashboard",
    })


@router.get("/appointments", name="agendatec.pages.coord.appointments")
async def coord_appointments_page(
    request: Request,
    user: dict = Depends(require_page_app("agendatec", perms=["agendatec.appointments.page.list"])),
):
    """Citas del día para el coordinador."""
    return render_agendatec(request, "agendatec/coord/appointments.html", {
        "title": "Coordinador - Citas del día",
    })


@router.get("/drops", name="agendatec.pages.coord.drops")
async def coord_drops_page(
    request: Request,
    user: dict = Depends(require_page_app("agendatec", perms=["agendatec.drops.page.list"])),
):
    """Vista de bajas del coordinador."""
    return render_agendatec(request, "agendatec/coord/drops.html", {
        "title": "Coordinador - Drops",
    })


@router.get("/slots", name="agendatec.pages.coord.slots")
async def coord_slots_page(
    request: Request,
    user: dict = Depends(require_page_app("agendatec", perms=["agendatec.slots.page.list"])),
):
    """Configuración de horario del coordinador."""
    return render_agendatec(request, "agendatec/coord/slots.html", {
        "title": "Coordinador - Horario",
    })
