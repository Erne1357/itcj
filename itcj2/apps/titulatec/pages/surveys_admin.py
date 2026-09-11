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
from itcj2.apps.titulatec.pages.nav import render_titulatec

logger = logging.getLogger("itcj2.apps.titulatec.pages.surveys_admin")
router = APIRouter(prefix="/admin/encuestas", tags=["titulatec-pages-surveys"])

_EXPORT = ["titulatec.survey.api.export"]
_LIST = ["titulatec.survey.page.list"]
_READ = ["titulatec.survey.api.read"]

_PAGE_SIZE = 50


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


def _forms(db):
    from itcj2.apps.titulatec.models import SurveyForm
    return (db.query(SurveyForm)
            .order_by(SurveyForm.code, SurveyForm.version.desc()).all())


def _body_ctx(db, *, form_id, page: int):
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import SurveyResponse

    forms = _forms(db)
    form = _resolve_form(db, form_id)
    ctx = {"forms": [{"id": f.id, "label": f"{f.code} v{f.version} ({f.status})"}
                     for f in forms],
           "form": form, "rows": [], "page": page, "has_more": False,
           "total": 0}
    if form is None:
        return ctx

    q = db.query(SurveyResponse).filter(SurveyResponse.form_id == form.id)
    ctx["total"] = q.count()
    rows = (q.order_by(SurveyResponse.submitted_at.desc(), SurveyResponse.id.desc())
            .offset((page - 1) * _PAGE_SIZE).limit(_PAGE_SIZE + 1).all())
    ctx["has_more"] = len(rows) > _PAGE_SIZE
    rows = rows[:_PAGE_SIZE]

    user_ids = {r.user_id for r in rows if r.user_id}
    users = ({u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
             if user_ids else {})
    for r in rows:
        u = users.get(r.user_id)
        ctx["rows"].append({
            "id": r.id,
            "submitted_at": r.submitted_at,
            "identity": r.identity_source,
            "control": r.control_number or (u.control_number if u else ""),
            "name": u.full_name if u else "Anónimo",
            "process_id": r.process_id,
        })
    return ctx


@router.get("", name="titulatec.pages.surveys.list")
async def list_responses(request: Request, form_id: str = "", page: str = "1",
                         user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, form_id=_to_int(form_id), page=max(1, _to_int(page) or 1))
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/surveys.html", ctx)


@router.get("/body", name="titulatec.pages.surveys.body")
async def body(request: Request, form_id: str = "", page: str = "1",
               user: dict = Depends(require_page_app("titulatec", perms=_LIST))):
    """Hermana de la página: acepta LOS MISMOS query params."""
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        ctx = _body_ctx(db, form_id=_to_int(form_id), page=max(1, _to_int(page) or 1))
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/partials/surveys_body.html", ctx)


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


@router.get("/{response_id}", name="titulatec.pages.surveys.detail")
async def detail(response_id: int, request: Request,
                 user: dict = Depends(require_page_app("titulatec", perms=_READ))):
    from itcj2.database import SessionLocal
    from itcj2.core.models.user import User
    from itcj2.apps.titulatec.models import SurveyForm, SurveyResponse

    db = SessionLocal()
    try:
        row = db.get(SurveyResponse, response_id)
        if row is None:
            return Response(status_code=404)
        form = db.get(SurveyForm, row.form_id)
        u = db.get(User, row.user_id) if row.user_id else None
        # El `schema` del SNAPSHOT: se etiquetan las respuestas con las
        # preguntas de la versión que se contestó, no con las de hoy.
        labels = {f.get("key"): f.get("label", f.get("key"))
                  for f in ((form.schema or {}).get("fields") or [])} if form else {}
        ctx = {
            "response": {
                "id": row.id, "submitted_at": row.submitted_at,
                "identity": row.identity_source,
                "control": row.control_number or (u.control_number if u else ""),
                "name": u.full_name if u else "Anónimo",
                "form_version": row.form_version,
            },
            "form": form,
            "items": [{"label": labels.get(k, k), "key": k, "value": v}
                      for k, v in (row.answers or {}).items()],
        }
    finally:
        db.close()
    return render_titulatec(request, "titulatec/admin/survey_detail.html", ctx)
