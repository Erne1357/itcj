"""Tablero de la jefa de Servicios Escolares (2026-10-14), SOLO LECTURA.

Permiso `titulatec.reports.page.view` (jefa de SE y `admin`). Rutas: `GET ""`
(página completa) y `GET /body` (solo `#tt-report-body`, para HTMX). Ambas `def`
(threadpool, convención R7): parsean `request.query_params` con
`ReportFilters.parse` (basura -> default, nunca 422), abren su `SessionLocal()`
y piden el contexto a `ReportService.build(..., today=db_now().date())`.
El contrato de llaves está en los docstrings de `services/report_service.py`;
la ruta solo agrega `generated_at`/`generated_at_text` (cabecera de impresión).
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request

from itcj2.apps.titulatec.pages.nav import render_titulatec
from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.titulatec.pages.reports_admin")
router = APIRouter(prefix="/admin/tablero", tags=["titulatec-pages-reports"])

_VIEW = ["titulatec.reports.page.view"]


def _stamp(ctx: dict, ahora: datetime) -> dict:
    """Fecha y hora de la consulta, para la cabecera de impresión (D4)."""
    ctx["generated_at"] = ahora
    ctx["generated_at_text"] = ahora.strftime("%d/%m/%Y %H:%M")
    return ctx


@router.get("", name="titulatec.pages.reports.home")
def home(request: Request,
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW))):
    from itcj2.apps.titulatec.services.report_service import (
        ReportFilters,
        ReportService,
    )
    from itcj2.core.utils.timezone import db_now
    from itcj2.database import SessionLocal

    filters = ReportFilters.parse(request.query_params)
    ahora = db_now()
    db = SessionLocal()
    try:
        ctx = ReportService.build(db, user_id=int(user["sub"]), filters=filters,
                                  today=ahora.date())
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/reports.html", _stamp(ctx, ahora))


@router.get("/body", name="titulatec.pages.reports.body")
def body(request: Request,
         user: dict = Depends(require_page_app("titulatec", perms=_VIEW))):
    from itcj2.apps.titulatec.services.report_service import (
        ReportFilters,
        ReportService,
    )
    from itcj2.core.utils.timezone import db_now
    from itcj2.database import SessionLocal

    filters = ReportFilters.parse(request.query_params)
    ahora = db_now()
    db = SessionLocal()
    try:
        ctx = ReportService.build(db, user_id=int(user["sub"]), filters=filters,
                                  today=ahora.date())
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/reports/_body.html",
                            _stamp(ctx, ahora))
