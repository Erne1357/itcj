"""
Stats API — Mantenimiento.

Endpoints: GET /api/maint/v2/stats/{global,by-technician,by-category,
                                    time-breakdown,ratings-detail,heatmap}
Permiso:   maint.stats.api.read

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

router = APIRouter(tags=["maint-stats"])
logger = logging.getLogger(__name__)


def _parse_date_range(from_str: str | None, to_str: str | None) -> tuple[date, date]:
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
# GET /stats/global
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/global")
def stats_global(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    user: dict = require_perms("maint", ["maint.stats.api.read"]),
    db: DbSession = None,
):
    """Totales y breakdowns por estado, categoría y prioridad."""
    from itcj2.apps.maint.services.stats_service import get_global_stats

    from_date, to_date = _parse_date_range(from_, to)
    try:
        return {"success": True, **get_global_stats(db, from_date, to_date, category_id)}
    except Exception as e:
        logger.error("Error en stats/global: %s", e)
        raise HTTPException(status_code=500, detail="Error al calcular estadísticas globales")


# ─────────────────────────────────────────────────────────────────────────────
# GET /stats/by-technician
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/by-technician")
def stats_by_technician(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    user: dict = require_perms("maint", ["maint.stats.api.read"]),
    db: DbSession = None,
):
    """Stats por técnico: asignados, resueltos, tiempo, rating, SLA."""
    from itcj2.apps.maint.services.stats_service import get_by_technician

    from_date, to_date = _parse_date_range(from_, to)
    try:
        return {"success": True, **get_by_technician(db, from_date, to_date, category_id)}
    except Exception as e:
        logger.error("Error en stats/by-technician: %s", e)
        raise HTTPException(status_code=500, detail="Error al calcular estadísticas por técnico")


# ─────────────────────────────────────────────────────────────────────────────
# GET /stats/by-category
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/by-category")
def stats_by_category(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    user: dict = require_perms("maint", ["maint.stats.api.read"]),
    db: DbSession = None,
):
    """Cantidad, abiertos, cerrados y tasa de cancelación por categoría."""
    from itcj2.apps.maint.services.stats_service import get_by_category

    from_date, to_date = _parse_date_range(from_, to)
    try:
        return {"success": True, **get_by_category(db, from_date, to_date, category_id)}
    except Exception as e:
        logger.error("Error en stats/by-category: %s", e)
        raise HTTPException(status_code=500, detail="Error al calcular estadísticas por categoría")


# ─────────────────────────────────────────────────────────────────────────────
# GET /stats/time-breakdown
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/time-breakdown")
def stats_time_breakdown(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    user: dict = require_perms("maint", ["maint.stats.api.read"]),
    db: DbSession = None,
):
    """Tiempo promedio en cada transición de estado (vía status_logs)."""
    from itcj2.apps.maint.services.stats_service import get_time_breakdown

    from_date, to_date = _parse_date_range(from_, to)
    try:
        return {"success": True, **get_time_breakdown(db, from_date, to_date, category_id)}
    except Exception as e:
        logger.error("Error en stats/time-breakdown: %s", e)
        raise HTTPException(status_code=500, detail="Error al calcular desglose de tiempos")


# ─────────────────────────────────────────────────────────────────────────────
# GET /stats/ratings-detail
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/ratings-detail")
def stats_ratings_detail(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    user: dict = require_perms("maint", ["maint.stats.api.read"]),
    db: DbSession = None,
):
    """Distribución de ratings y % rating_efficiency."""
    from itcj2.apps.maint.services.stats_service import get_ratings_detail

    from_date, to_date = _parse_date_range(from_, to)
    try:
        return {"success": True, **get_ratings_detail(db, from_date, to_date, category_id)}
    except Exception as e:
        logger.error("Error en stats/ratings-detail: %s", e)
        raise HTTPException(status_code=500, detail="Error al calcular detalle de calificaciones")


# ─────────────────────────────────────────────────────────────────────────────
# GET /stats/heatmap
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/heatmap")
def stats_heatmap(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    group_by: str = Query(default="location"),
    user: dict = require_perms("maint", ["maint.stats.api.read"]),
    db: DbSession = None,
):
    """Heatmap de tickets por ubicación×categoría o edificio×mes."""
    from itcj2.apps.maint.services.stats_service import (
        get_heatmap_by_location,
        get_heatmap_by_building,
    )

    if group_by not in ("location", "building"):
        raise HTTPException(status_code=400, detail="group_by debe ser 'location' o 'building'")

    from_date, to_date = _parse_date_range(from_, to)
    try:
        if group_by == "building":
            return {"success": True, **get_heatmap_by_building(db, from_date, to_date, category_id)}
        return {"success": True, **get_heatmap_by_location(db, from_date, to_date, category_id)}
    except Exception as e:
        logger.error("Error en stats/heatmap: %s", e)
        raise HTTPException(status_code=500, detail="Error al generar heatmap")
