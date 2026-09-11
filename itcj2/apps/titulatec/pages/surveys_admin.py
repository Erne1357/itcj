"""Bandeja de respuestas de encuestas + exportación CSV (Servicios Escolares).

ORDEN DE DECLARACIÓN — invariante del archivo: `/export.csv` y `/body` van
SIEMPRE antes que `/{response_id}`. FastAPI resuelve en orden de declaración y
`{response_id}: int` no "falla hacia la siguiente ruta": `solve_dependencies`
llama las sub-dependencias ANTES de validar los path params, así que un
`/export.csv` declarado por debajo devuelve 403 al actor que solo tiene
`survey.api.export` (le falta el `survey.api.read` del detalle) y 422 al que sí
tiene `read`. Nunca 404, y nunca el CSV.

El escapado contra inyección de fórmulas NO vive aquí: es `escape_formula`, a
nivel de módulo en `services/survey_service.py` (Tarea 10), y
`SurveyService.export_rows` ya lo aplica a TODA celda (§8.2). Esta ruta solo
serializa lo que el servicio le devuelve.
"""
import csv
import io
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from itcj2.dependencies import require_page_app

logger = logging.getLogger("itcj2.apps.titulatec.pages.surveys_admin")
router = APIRouter(prefix="/admin/encuestas", tags=["titulatec-pages-surveys"])

_EXPORT = ["titulatec.survey.api.export"]


def _to_int(raw):
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _resolve_form(db, form_id):
    """El formulario pedido, o el más reciente si no se pidió ninguno."""
    from itcj2.apps.titulatec.models import SurveyForm
    if form_id:
        return db.get(SurveyForm, form_id)
    return (db.query(SurveyForm)
            .order_by(SurveyForm.status.desc(), SurveyForm.version.desc(),
                      SurveyForm.id.desc())
            .first())


@router.get("/export.csv", name="titulatec.pages.surveys.export")
async def export(request: Request, form_id: str = "",
                 user: dict = Depends(require_page_app("titulatec", perms=_EXPORT))):
    """CSV de todas las respuestas del formulario.

    Las celdas ya vienen escapadas contra inyección de fórmulas desde
    `SurveyService.export_rows`: es la primera vez que el repo exporta contenido
    de autor NO CONFIABLE (§8.2), y quien lo abre en Excel es admin de titulatec.
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.titulatec.services.survey_service import SurveyService

    db = SessionLocal()
    try:
        form = _resolve_form(db, _to_int(form_id))
        if form is None:
            return Response(status_code=404)
        headers, rows = SurveyService.export_rows(db, form.id)
        code, version = form.code, form.version
    finally:
        db.close()

    output = io.StringIO()
    output.write("﻿")  # BOM UTF-8 para Excel en Windows
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)

    filename = (f"encuesta-{code}-v{version}-"
                f"{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.csv")
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
