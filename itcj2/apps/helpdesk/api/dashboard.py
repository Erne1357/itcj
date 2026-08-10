"""
Dashboard API — resumen del panel de administrador de Help-Desk.

`GET /admin-overview` expone en JSON los mismos datos que ya renderiza
server-side `/help-desk/admin/home` (ambos llaman a `AdminDashboardService`,
así que la página y este endpoint nunca divergen). Existe para el botón
"Actualizar" de la página, que re-navega vía `HelpdeskPage.refresh()` — un
morph GET a la misma URL que vuelve a componer todo en el servidor — y para
cualquier otro consumidor que necesite el mismo resumen en JSON (tests, un
futuro widget móvil, etc.).
"""
import logging

from fastapi import APIRouter, HTTPException

from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["helpdesk-dashboard"])
logger = logging.getLogger(__name__)


@router.get("/admin-overview")
def get_admin_overview(
    user: dict = require_perms("helpdesk", ["helpdesk.dashboard.admin"]),
    db: DbSession = None,
):
    """KPIs, banda de atención y actividad reciente de `/help-desk/admin/home`.

    Mismo permiso que la página (`helpdesk.dashboard.admin`); el scope de cada
    conteo lo resuelve `AdminDashboardService` internamente (fail-closed sin
    departamento resoluble — nunca 403 por eso, solo conteos en 0).
    """
    from itcj2.apps.helpdesk.services.admin_dashboard_service import AdminDashboardService

    try:
        data = AdminDashboardService.get_overview(db, user)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Error al componer el overview del dashboard admin: {e}")
        raise HTTPException(status_code=500, detail="Error interno")
