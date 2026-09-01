"""
Páginas de administración para Prorrogas.
Equivalente a itcj/apps/prorrogas_tec/routes/pages/admin.py.

Rutas:
  GET /prorrogas_tec/admin/home                        → Dashboard de admin
  GET /prorrogas_tec/admin/users                       → Gestión de usuarios
  GET /prorrogas_tec/admin/requests                    → Solicitudes
  GET /prorrogas_tec/admin/requests/create             → Crear solicitud
  GET /prorrogas_tec/admin/reports                     → Reportes
  GET /prorrogas_tec/admin/periods                     → Períodos académicos
  GET /prorrogas_tec/admin/periods/{period_id}/days    → Configurar días de período
"""
import logging

from fastapi import APIRouter, Depends, Request

from itcj2.apps.prorrogas_tec.pages.nav import render_prorrogas_tec
from itcj2.dependencies import require_page_app, require_page_roles

logger = logging.getLogger("itcj2.apps.prorrogas_tec.pages.admin")

# ---------------------------------------------------------------------------
# Guard a nivel de ROUTER (ver la nota equivalente en api/periods.py).
#
# Las tres paginas de admin llegaron con su `require_page_app` COMENTADO: el
# dashboard, las solicitudes y los periodos se servian a cualquiera, con sesion
# o sin ella. `require_page_roles` redirige al login en vez de devolver un 401
# JSON, que es lo correcto para HTML.
#
# TODO(prorrogas): permisos granulares por pagina
# (`prorrogas_tec.{modulo}.page.{accion}`) cuando el modelo de roles exista.
# Ver itcj2/apps/prorrogas_tec/docs/PENDIENTES.md
# ---------------------------------------------------------------------------
router = APIRouter(
    prefix="/admin",
    tags=["prorrogas_tec-pages-admin"],
    dependencies=[Depends(require_page_roles("prorrogas_tec", ["admin"]))],
)


@router.get("/home", name="prorrogas_tec.pages.admin.home")
async def admin_home(
    request: Request,
    # user: dict = Depends(require_page_app("prorrogas_tec", perms=["prorrogas_tec.admin_dashboard.page.view"])),
):
    """Dashboard principal de administrador de AgendaTec."""
    return render_prorrogas_tec(request, "prorrogas_tec/admin/home.html", {
        "page_title": "Admin · Dashboard",
    })


@router.get("/requests", name="prorrogas_tec.pages.admin.requests")
async def admin_requests(
    request: Request,
    # user: dict = Depends(require_page_app("agendatec", perms=["prorrogas.requests.page.list"])),
):
    """Vista de todas las solicitudes (admin)."""
    return render_prorrogas_tec(request, "prorrogas_tec/admin/request.html", {
        "page_title": "Admin · Solicitudes",
    })

@router.get("/periods", name="prorrogas_tec.pages.admin.periods")
async def admin_periods(
    request: Request,
    # user: dict = Depends(require_page_app("prorrogas_tec", perms=["prorrogas_tec.periods.page.list"])),
):
    """Gestión de períodos académicos."""
    return render_prorrogas_tec(request, "prorrogas_tec/admin/periods.html", {
        "page_title": "Admin · Períodos Académicos",
    })


# @router.get("/requests/create", name="agendatec.pages.admin.create_request")
# async def admin_create_request(
#     request: Request,
#     user: dict = Depends(require_page_app("agendatec", perms=["agendatec.requests.page.create"])),
# ):
#     """Formulario para crear solicitud manualmente (admin)."""
#     return render_agendatec(request, "agendatec/admin/create_request.html", {
#         "page_title": "Admin · Crear Solicitud",
#     })


# @router.get("/reports", name="agendatec.pages.admin.reports")
# async def admin_reports(
#     request: Request,
#     user: dict = Depends(require_page_app("agendatec", perms=["agendatec.reports.page.view"])),
# ):
#     """Reportes del sistema AgendaTec."""
#     return render_agendatec(request, "agendatec/admin/reports.html", {
#         "page_title": "Admin · Reportes",
#     })


# @router.get("/periods/{period_id}/days", name="agendatec.pages.admin.period_days")
# async def admin_period_days(
#     request: Request,
#     period_id: int,
#     user: dict = Depends(require_page_app("agendatec", perms=["agendatec.periods.page.edit"])),
# ):
#     """Configuración de días hábiles de un período académico."""
#     return render_agendatec(request, "agendatec/admin/period_days.html", {
#         "page_title": "Admin · Configurar Días",
#         "period_id": period_id,
#     })
