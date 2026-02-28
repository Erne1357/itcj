"""
Reports API v2 — 4 endpoints (reportes y estadísticas).
Fuente: itcj/apps/vistetec/routes/api/reports.py
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["vistetec-reports"])
logger = logging.getLogger(__name__)


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parsea fecha desde query param (YYYY-MM-DD). Retorna None si inválida."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None


@router.get("/dashboard")
def get_dashboard_summary(
    user: dict = require_perms("vistetec", ["vistetec.reports.api.dashboard"]),
    db: DbSession = None,
):
    """Resumen general para el dashboard."""
    from itcj.apps.vistetec.services import reports_service

    return reports_service.get_dashboard_summary()


@router.get("/garments")
def get_garment_report(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = require_perms("vistetec", ["vistetec.reports.api.view"]),
    db: DbSession = None,
):
    """Reporte de prendas con filtro de fechas."""
    from itcj.apps.vistetec.services import reports_service

    return reports_service.get_garment_report(
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
    )


@router.get("/donations")
def get_donation_report(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = require_perms("vistetec", ["vistetec.reports.api.view"]),
    db: DbSession = None,
):
    """Reporte de donaciones con filtro de fechas."""
    from itcj.apps.vistetec.services import reports_service

    return reports_service.get_donation_report(
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
    )


@router.get("/appointments")
def get_appointment_report(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = require_perms("vistetec", ["vistetec.reports.api.view"]),
    db: DbSession = None,
):
    """Reporte de citas con filtro de fechas."""
    from itcj.apps.vistetec.services import reports_service

    return reports_service.get_appointment_report(
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
    )


@router.get("/activity")
def get_recent_activity(
    limit: int = 15,
    user: dict = require_perms("vistetec", ["vistetec.reports.api.dashboard"]),
    db: DbSession = None,
):
    """Actividad reciente configurable por límite."""
    from itcj.apps.vistetec.services import reports_service

    return reports_service.get_recent_activity(limit=limit)
