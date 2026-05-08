"""
Admin API — Mantenimiento.

Endpoints administrativos de bajo volumen que no encajan en los routers
específicos de tickets, categorías, etc.

Rutas expuestas:
  POST /api/maint/v2/admin/sla/check
      Dispara manualmente el chequeo de SLA overdue.
      Útil para QA y validación sin esperar el ciclo de cron.
      Permiso requerido: maint.admin.api.reports
"""
import logging

from fastapi import APIRouter, HTTPException

from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["maint-admin"])
logger = logging.getLogger(__name__)


@router.post("/sla/check")
def trigger_sla_check(
    user: dict = require_perms("maint", ["maint.admin.api.reports"]),
    db: DbSession = None,
):
    """
    Dispara el chequeo de SLA overdue de forma síncrona y devuelve el resumen.
    Equivalente a ejecutar el script maint_sla_check.py manualmente.
    """
    from itcj2.apps.maint.services.sla_service import run_overdue_check

    try:
        result = run_overdue_check(db)
        return {"success": True, "data": result}
    except Exception as exc:
        logger.error("Error en trigger manual de SLA check (user %s): %s", user.get("sub"), exc)
        raise HTTPException(status_code=500, detail="Error ejecutando SLA check")
