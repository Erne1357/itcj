"""
Páginas de administración para AgendaTec.
Equivalente a itcj/apps/agendatec/routes/pages/admin.py.

Rutas:
  GET /agendatec/admin/home                        → Dashboard de admin
  GET /agendatec/admin/users                       → Gestión de usuarios
  GET /agendatec/admin/requests                    → Solicitudes
  GET /agendatec/admin/requests/create             → Crear solicitud
  GET /agendatec/admin/reports                     → Reportes
  GET /agendatec/admin/periods                     → Períodos académicos
  GET /agendatec/admin/periods/{period_id}/days    → Configurar días de período
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.apps.agendatec.pages.nav import render_agendatec
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.agendatec.pages.admin")

router = APIRouter(prefix="/admin", tags=["agendatec-pages-admin"])


@router.get("/home", name="agendatec.pages.admin.home")
async def admin_home(
    request: Request,
    user: dict = Depends(require_page_app("agendatec", perms=["agendatec.admin_dashboard.page.view"])),
):
    """Dashboard principal de administrador de AgendaTec."""
    return render_agendatec(request, "agendatec/admin/home.html", {
        "page_title": "Admin · Dashboard",
    })


@router.get("/users", name="agendatec.pages.admin.users")
async def admin_users(
    request: Request,
    user: dict = Depends(require_page_app("agendatec", perms=["agendatec.users.page.list"])),
):
    """Gestión de usuarios de AgendaTec."""
    return render_agendatec(request, "agendatec/admin/users.html", {
        "page_title": "Admin · Usuarios",
    })


@router.get("/requests", name="agendatec.pages.admin.requests")
async def admin_requests(
    request: Request,
    user: dict = Depends(require_page_app("agendatec", perms=["agendatec.requests.page.list"])),
):
    """Vista de todas las solicitudes (admin)."""
    return render_agendatec(request, "agendatec/admin/requests.html", {
        "page_title": "Admin · Solicitudes",
    })


@router.get("/requests/create", name="agendatec.pages.admin.create_request")
async def admin_create_request(
    request: Request,
    user: dict = Depends(require_page_app("agendatec", perms=["agendatec.requests.page.create"])),
):
    """Formulario para crear solicitud manualmente (admin)."""
    return render_agendatec(request, "agendatec/admin/create_request.html", {
        "page_title": "Admin · Crear Solicitud",
    })


@router.get("/reports", name="agendatec.pages.admin.reports")
async def admin_reports(
    request: Request,
    user: dict = Depends(require_page_app("agendatec", perms=["agendatec.reports.page.view"])),
):
    """Reportes del sistema AgendaTec."""
    return render_agendatec(request, "agendatec/admin/reports.html", {
        "page_title": "Admin · Reportes",
    })


@router.get("/periods", name="agendatec.pages.admin.periods")
async def admin_periods(
    request: Request,
    user: dict = Depends(require_page_app("agendatec", perms=["agendatec.periods.page.list"])),
):
    """Gestión de períodos académicos."""
    return render_agendatec(request, "agendatec/admin/periods.html", {
        "page_title": "Admin · Períodos Académicos",
    })


@router.get("/periods/{period_id}/days", name="agendatec.pages.admin.period_days")
async def admin_period_days(
    request: Request,
    period_id: int,
    user: dict = Depends(require_page_app("agendatec", perms=["agendatec.periods.page.edit"])),
):
    """Configuración de días hábiles de un período académico."""
    return render_agendatec(request, "agendatec/admin/period_days.html", {
        "page_title": "Admin · Configurar Días",
        "period_id": period_id,
    })
