"""
Páginas de voluntario para VisteTec.
Equivalente a itcj/apps/vistetec/routes/pages/volunteer.py.

Rutas:
  GET /vistetec/volunteer/dashboard                 → Dashboard del voluntario
  GET /vistetec/volunteer/garment/new               → Registrar nueva prenda
  GET /vistetec/volunteer/garment/{id}/edit         → Editar prenda
  GET /vistetec/volunteer/appointments              → Gestión de citas
  GET /vistetec/volunteer/donations/register        → Registrar donación
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.apps.vistetec.pages.nav import render_vistetec
from itcj2.dependencies import require_page_app, require_page_roles

logger = logging.getLogger("itcj2.apps.vistetec.pages.volunteer")

router = APIRouter(prefix="/volunteer", tags=["vistetec-pages-volunteer"])


@router.get("/dashboard", name="vistetec.pages.volunteer.dashboard")
async def dashboard(
    request: Request,
    user: dict = Depends(require_page_roles("vistetec", ["volunteer", "admin"])),
):
    """Dashboard del voluntario."""
    return render_vistetec(request, "vistetec/volunteer/dashboard.html", {
        "title": "Dashboard Voluntario",
    })


@router.get("/garment/new", name="vistetec.pages.volunteer.garment_form")
async def garment_form(
    request: Request,
    user: dict = Depends(require_page_app("vistetec", perms=["vistetec.garments.page.create"])),
):
    """Formulario para registrar nueva prenda."""
    return render_vistetec(request, "vistetec/volunteer/garment_form.html", {
        "title": "Registrar Prenda",
    })


@router.get("/garment/{garment_id}/edit", name="vistetec.pages.volunteer.garment_edit")
async def garment_edit(
    request: Request,
    garment_id: int,
    user: dict = Depends(require_page_app("vistetec", perms=["vistetec.garments.page.edit"])),
):
    """Formulario para editar prenda existente."""
    return render_vistetec(request, "vistetec/volunteer/garment_form.html", {
        "title": "Editar Prenda",
        "garment_id": garment_id,
    })


@router.get("/appointments", name="vistetec.pages.volunteer.appointments")
async def appointments(
    request: Request,
    user: dict = Depends(require_page_app("vistetec", perms=["vistetec.appointments.page.manage"])),
):
    """Gestión de citas del voluntario."""
    return render_vistetec(request, "vistetec/volunteer/appointments.html", {
        "title": "Gestión de Citas",
    })


@router.get("/donations/register", name="vistetec.pages.volunteer.register_donation")
async def register_donation(
    request: Request,
    user: dict = Depends(require_page_app("vistetec", perms=["vistetec.donations.page.register"])),
):
    """Formulario para registrar donación."""
    return render_vistetec(request, "vistetec/volunteer/register_donation.html", {
        "title": "Registrar Donación",
    })
