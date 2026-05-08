"""
Dashboard API — Mantenimiento.

Endpoint: GET /api/maint/v2/dashboard
Permiso: maint.tickets.api.read.own  (cualquier usuario con acceso a maint)

Los datos devueltos están filtrados según el scope de visibilidad del usuario:
  - admin / dispatcher / tech_maint → todos los tickets
  - department_head / secretary     → su departamento
  - staff / resto                   → solo sus propios tickets
"""
import logging

from fastapi import APIRouter, HTTPException

from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["maint-dashboard"])
logger = logging.getLogger(__name__)


@router.get("")
def get_dashboard(
    user: dict = require_perms("maint", ["maint.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.apps.maint.services.dashboard_service import get_dashboard as _get_dashboard

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "maint")

    try:
        data = _get_dashboard(db=db, user_id=user_id, user_roles=user_roles)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error("Error calculando dashboard maint para user %s: %s", user_id, e)
        raise HTTPException(status_code=500, detail="Error al cargar el dashboard")
