"""
Reports API — Mantenimiento.

Endpoints: GET /api/maint/v2/reports/{tickets,technicians,categories,sla}
Permiso:   maint.admin.api.reports  (reusa la asignación existente)

Parámetros comunes:
    from        YYYY-MM-DD  (default: hoy - 30 días)
    to          YYYY-MM-DD  (default: hoy)
    category_id int opcional
"""
import logging
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.maint.utils.timezone_utils import now_local

router = APIRouter(tags=["maint-reports"])
logger = logging.getLogger(__name__)


def _parse_date_range(from_str: str | None, to_str: str | None) -> tuple[date, date]:
    """Parsea y valida el rango de fechas. Aplica defaults si no se proveen."""
    today = now_local().date()

    try:
        to_date = date.fromisoformat(to_str) if to_str else today
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Formato de fecha inválido para 'to': {to_str}")

    try:
        from_date = date.fromisoformat(from_str) if from_str else today - timedelta(days=30)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Formato de fecha inválido para 'from': {from_str}")

    if from_date > to_date:
        raise HTTPException(status_code=400, detail="'from' no puede ser posterior a 'to'")

    return from_date, to_date


# ─────────────────────────────────────────────────────────────────────────────
# GET /reports/tickets
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/tickets")
def reports_tickets(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    user: dict = require_perms("maint", ["maint.admin.api.reports"]),
    db: DbSession = None,
):
    """Serie de tiempo de tickets creados vs resueltos por día."""
    from itcj2.apps.maint.services.reports_service import get_tickets_time_series

    from_date, to_date = _parse_date_range(from_, to)
    try:
        return {"success": True, **get_tickets_time_series(db, from_date, to_date, category_id)}
    except Exception as e:
        logger.error("Error en reports/tickets: %s", e)
        raise HTTPException(status_code=500, detail="Error al generar reporte de tickets")


# ─────────────────────────────────────────────────────────────────────────────
# GET /reports/technicians
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/technicians")
def reports_technicians(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    user: dict = require_perms("maint", ["maint.admin.api.reports"]),
    db: DbSession = None,
):
    """Agregados por técnico en el período."""
    from itcj2.apps.maint.services.reports_service import get_technician_report

    from_date, to_date = _parse_date_range(from_, to)
    try:
        return {"success": True, **get_technician_report(db, from_date, to_date, category_id)}
    except Exception as e:
        logger.error("Error en reports/technicians: %s", e)
        raise HTTPException(status_code=500, detail="Error al generar reporte de técnicos")


# ─────────────────────────────────────────────────────────────────────────────
# GET /reports/categories
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/categories")
def reports_categories(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    user: dict = require_perms("maint", ["maint.admin.api.reports"]),
    db: DbSession = None,
):
    """Agregados por categoría en el período."""
    from itcj2.apps.maint.services.reports_service import get_category_report

    from_date, to_date = _parse_date_range(from_, to)
    try:
        return {"success": True, **get_category_report(db, from_date, to_date, category_id)}
    except Exception as e:
        logger.error("Error en reports/categories: %s", e)
        raise HTTPException(status_code=500, detail="Error al generar reporte de categorías")


# ─────────────────────────────────────────────────────────────────────────────
# GET /reports/sla
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/sla")
def reports_sla(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    user: dict = require_perms("maint", ["maint.admin.api.reports"]),
    db: DbSession = None,
):
    """Resumen de cumplimiento SLA para tickets resueltos en el rango."""
    from itcj2.apps.maint.services.reports_service import get_sla_report

    from_date, to_date = _parse_date_range(from_, to)
    try:
        return {"success": True, **get_sla_report(db, from_date, to_date, category_id)}
    except Exception as e:
        logger.error("Error en reports/sla: %s", e)
        raise HTTPException(status_code=500, detail="Error al generar reporte SLA")
