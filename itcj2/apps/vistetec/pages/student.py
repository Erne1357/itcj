"""
Páginas de estudiante para VisteTec.
Equivalente a itcj/apps/vistetec/routes/pages/student.py.

Rutas:
  GET /vistetec/student/catalog              → Catálogo de prendas
  GET /vistetec/student/catalog/{id}         → Detalle de prenda
  GET /vistetec/student/my-appointments      → Mis citas
  GET /vistetec/student/my-donations         → Mis donaciones
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.apps.vistetec.pages.nav import render_vistetec
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.vistetec.pages.student")

router = APIRouter(prefix="/student", tags=["vistetec-pages-student"])


@router.get("/catalog", name="vistetec.pages.student.catalog")
async def catalog(
    request: Request,
    user: dict = Depends(require_page_app("vistetec", perms=["vistetec.catalog.page.view"])),
):
    """Página principal del catálogo de prendas."""
    return render_vistetec(request, "vistetec/student/catalog.html", {"title": "Catálogo"})


@router.get("/catalog/{garment_id}", name="vistetec.pages.student.garment_detail")
async def garment_detail(
    request: Request,
    garment_id: int,
    user: dict = Depends(require_page_app("vistetec", perms=["vistetec.catalog.page.detail"])),
):
    """Detalle de una prenda del catálogo."""
    return render_vistetec(request, "vistetec/student/garment_detail.html", {
        "title": "Detalle de Prenda",
        "garment_id": garment_id,
    })


@router.get("/my-appointments", name="vistetec.pages.student.my_appointments")
async def my_appointments(
    request: Request,
    user: dict = Depends(require_page_app("vistetec", perms=["vistetec.appointments.page.my"])),
):
    """Citas del estudiante."""
    return render_vistetec(request, "vistetec/student/my_appointments.html", {
        "title": "Mis Citas",
    })


@router.get("/my-donations", name="vistetec.pages.student.my_donations")
async def my_donations(
    request: Request,
    user: dict = Depends(require_page_app("vistetec", perms=["vistetec.donations.page.my"])),
):
    """Donaciones del estudiante."""
    return render_vistetec(request, "vistetec/student/my_donations.html", {
        "title": "Mis Donaciones",
    })
