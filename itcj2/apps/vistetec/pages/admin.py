"""
Páginas administrativas de VisteTec.
Equivalente a itcj/apps/vistetec/routes/pages/admin.py.

Rutas:
  GET /vistetec/admin/dashboard  → Dashboard administrativo
  GET /vistetec/admin/garments   → Gestión de prendas
  GET /vistetec/admin/pantry     → Dashboard de despensa
  GET /vistetec/admin/campaigns  → Gestión de campañas
  GET /vistetec/admin/reports    → Reportes y estadísticas
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.apps.vistetec.pages.nav import render_vistetec
from itcj2.dependencies import require_page_app, require_page_roles

logger = logging.getLogger("itcj2.apps.vistetec.pages.admin")

router = APIRouter(prefix="/admin", tags=["vistetec-pages-admin"])


@router.get("/dashboard", name="vistetec.pages.admin.dashboard")
async def dashboard(
    request: Request,
    user: dict = Depends(require_page_roles("vistetec", ["admin"])),
):
    """Dashboard administrativo de VisteTec."""
    return render_vistetec(request, "vistetec/admin/dashboard.html", {
        "title": "Dashboard Admin",
    })


@router.get("/garments", name="vistetec.pages.admin.garments")
async def garments(
    request: Request,
    user: dict = Depends(require_page_app("vistetec", perms=["vistetec.garments.page.list"])),
):
    """Lista completa de prendas (todos los estados)."""
    return render_vistetec(request, "vistetec/admin/garments.html", {
        "title": "Gestión de Prendas",
    })


@router.get("/pantry", name="vistetec.pages.admin.pantry")
async def pantry(
    request: Request,
    user: dict = Depends(require_page_app("vistetec", perms=["vistetec.pantry.page.dashboard"])),
):
    """Dashboard de despensa."""
    return render_vistetec(request, "vistetec/admin/pantry.html", {
        "title": "Despensa",
    })


@router.get("/campaigns", name="vistetec.pages.admin.campaigns")
async def campaigns(
    request: Request,
    user: dict = Depends(require_page_app("vistetec", perms=["vistetec.pantry.page.campaigns"])),
):
    """Gestión de campañas."""
    return render_vistetec(request, "vistetec/admin/campaigns.html", {
        "title": "Campañas",
    })


@router.get("/reports", name="vistetec.pages.admin.reports")
async def reports(
    request: Request,
    user: dict = Depends(require_page_app("vistetec", perms=["vistetec.reports.page.reports"])),
):
    """Reportes y estadísticas de VisteTec."""
    return render_vistetec(request, "vistetec/admin/reports.html", {
        "title": "Reportes",
    })
