"""
Analysis API — Mantenimiento.

Endpoints: GET /api/maint/v2/analysis/{outliers,kmeans,distribution,trends}
Permiso:   maint.analysis.api.read

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

router = APIRouter(tags=["maint-analysis"])
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
# GET /analysis/outliers
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/outliers")
def analysis_outliers(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    metric: str = Query(default="time_invested"),
    user: dict = require_perms("maint", ["maint.analysis.api.read"]),
    db: DbSession = None,
):
    """Detección de outliers por IQR. Métricas: time_invested, rating_attention, rating_speed."""
    from itcj2.apps.maint.services.analysis_service import get_outliers

    from_date, to_date = _parse_date_range(from_, to)
    try:
        return {"success": True, **get_outliers(db, from_date, to_date, metric, category_id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error en analysis/outliers: %s", e)
        raise HTTPException(status_code=500, detail="Error al calcular outliers")


# ─────────────────────────────────────────────────────────────────────────────
# GET /analysis/kmeans
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/kmeans")
def analysis_kmeans(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    k: int = Query(default=3),
    user: dict = require_perms("maint", ["maint.analysis.api.read"]),
    db: DbSession = None,
):
    """K-means sobre tickets resueltos. Vectores: [time_invested_norm, rating_attention, rating_speed]."""
    from itcj2.apps.maint.services.analysis_service import get_kmeans

    from_date, to_date = _parse_date_range(from_, to)
    try:
        return {"success": True, **get_kmeans(db, from_date, to_date, k, category_id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error en analysis/kmeans: %s", e)
        raise HTTPException(status_code=500, detail="Error al ejecutar K-means")


# ─────────────────────────────────────────────────────────────────────────────
# GET /analysis/distribution
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/distribution")
def analysis_distribution(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    metric: str = Query(default="time_invested"),
    bins: int = Query(default=10),
    user: dict = require_perms("maint", ["maint.analysis.api.read"]),
    db: DbSession = None,
):
    """Histograma de distribución. Métricas: time_invested, rating_attention, rating_speed."""
    from itcj2.apps.maint.services.analysis_service import get_distribution

    from_date, to_date = _parse_date_range(from_, to)
    try:
        return {"success": True, **get_distribution(db, from_date, to_date, metric, bins, category_id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error en analysis/distribution: %s", e)
        raise HTTPException(status_code=500, detail="Error al calcular distribución")


# ─────────────────────────────────────────────────────────────────────────────
# GET /analysis/trends
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/trends")
def analysis_trends(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    granularity: str = Query(default="day"),
    user: dict = require_perms("maint", ["maint.analysis.api.read"]),
    db: DbSession = None,
):
    """Serie temporal de creación, resolución y cancelación. Granularidad: day, week, month."""
    from itcj2.apps.maint.services.analysis_service import get_trends

    from_date, to_date = _parse_date_range(from_, to)
    try:
        return {"success": True, **get_trends(db, from_date, to_date, granularity, category_id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error en analysis/trends: %s", e)
        raise HTTPException(status_code=500, detail="Error al calcular tendencias")
