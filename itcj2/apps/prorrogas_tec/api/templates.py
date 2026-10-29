"""Plantillas de los formatos (vista Documentos de la secretaría).

Rutas bajo ``/api/prorrogas/v2/templates``. Todas son ``def`` (no ``async``):
LibreOffice y la lectura del ``.docx`` bloquean, y FastAPI las corre en el
threadpool. Los errores responden ``{"error", "message", ...detalle}`` en la
raíz del JSON (no dentro de ``detail``), con los códigos de ``TemplateError``.
"""
import logging
from typing import Optional

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from itcj2.apps.prorrogas_tec.documents.catalog import DOC_TYPES, default_template_path, sample_values
from itcj2.apps.prorrogas_tec.services.docx_fill import fill_docx
from itcj2.apps.prorrogas_tec.services.template_service import (
    MAX_TEMPLATE_BYTES, YEAR_MAX, YEAR_MIN, TemplateError, TemplateService,
)
from itcj2.apps.prorrogas_tec.models.template import ProrrogaTemplate
from itcj2.core.utils import docx_pdf
from itcj2.core.utils.timezone import db_now
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["prorrogas_tec-templates"])
logger = logging.getLogger(__name__)

_READ = ["prorrogas_tec.templates.api.read"]
_UPLOAD = ["prorrogas_tec.templates.api.upload"]

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_KIND = "prorrogas_documento"


def _error(status: int, code: str, message: str, **detail) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message, **detail})


def _template_out(t: ProrrogaTemplate) -> dict:
    return {
        "id": t.id,
        "anio": t.year,
        "original_name": t.original_name,
        "uploaded_at": t.uploaded_at.isoformat() if t.uploaded_at else None,
        "size_bytes": t.size_bytes,
    }


@router.get("", name="prorrogas_tec.api.templates.list")
def list_templates(db: DbSession, user: dict = require_perms("prorrogas_tec", _READ)):
    """Los 6 formatos y, por año, la plantilla que se usa en cada uno."""
    anios = []
    for anio in TemplateService.years(db, current_year=db_now().year):
        plantillas = []
        for code, tipo in DOC_TYPES.items():
            t = TemplateService.active(db, code, anio)
            origen = "sistema" if t is None else ("subida" if t.year == anio else "heredada")
            plantillas.append({
                "doc_type": code,
                "label": tipo.label,
                "origen": origen,
                "plantilla": _template_out(t) if t is not None else None,
            })
        anios.append({"anio": anio, "plantillas": plantillas})
    return {
        "tipos": [
            {"code": t.code, "label": t.label,
             "obligatorios": sorted(t.required), "permitidos": sorted(t.allowed)}
            for t in DOC_TYPES.values()
        ],
        "anios": anios,
    }


@router.post("", status_code=201, name="prorrogas_tec.api.templates.upload")
def upload_template(
    db: DbSession,
    doc_type: str = Form(...),
    anio: int = Form(...),
    archivo: UploadFile = File(...),
    user: dict = require_perms("prorrogas_tec", _UPLOAD),
):
    # Uno de más basta para saber que se pasó del tope sin leer un archivo enorme.
    data = archivo.file.read(MAX_TEMPLATE_BYTES + 1)
    try:
        t = TemplateService.upload(
            db, doc_type=doc_type, year=anio, filename=archivo.filename or "",
            data=data, actor_id=int(user["sub"]),
        )
    except TemplateError as e:
        return _error(400, e.code, e.message, **e.detail)
    logger.info("Plantilla de prórrogas subida", extra={
        "template_id": t.id, "doc_type": t.doc_type, "year": t.year,
    })
    return {"id": t.id, "doc_type": t.doc_type, "anio": t.year,
            "original_name": t.original_name, "placeholders": t.placeholders}


@router.get("/sistema/{doc_type}/archivo", name="prorrogas_tec.api.templates.system_file")
def system_template_file(doc_type: str, user: dict = require_perms("prorrogas_tec", _READ)):
    if doc_type not in DOC_TYPES:
        return _error(404, "tipo_invalido", "El tipo de documento no existe.")
    return Response(
        content=default_template_path(doc_type).read_bytes(),
        media_type=DOCX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{doc_type}.docx"'},
    )


@router.get("/vista-previa/{doc_type}.pdf", name="prorrogas_tec.api.templates.preview")
def preview_template(
    doc_type: str,
    db: DbSession,
    anio: Optional[int] = Query(None),
    user: dict = require_perms("prorrogas_tec", _READ),
):
    """La plantilla en uso para ``doc_type`` y ``anio``, llena con datos de ejemplo."""
    if doc_type not in DOC_TYPES:
        return _error(404, "tipo_invalido", "El tipo de documento no existe.")
    anio = anio or db_now().year
    if not YEAR_MIN <= anio <= YEAR_MAX:
        return _error(400, "anio_invalido", f"El año debe estar entre {YEAR_MIN} y {YEAR_MAX}.")
    data, _ = TemplateService.resolve(db, doc_type, anio)
    filled = fill_docx(data, *sample_values(doc_type))
    try:
        pdf = docx_pdf.docx_to_pdf(filled, kind=PDF_KIND)
    except docx_pdf.PdfConversionError:
        logger.exception("Vista previa de plantilla sin PDF", extra={"doc_type": doc_type, "year": anio})
        return _error(503, "pdf_no_disponible",
                      "No se pudo generar el PDF. Intenta de nuevo o descarga la plantilla.")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="vista-previa-{doc_type}-{anio}.pdf"'},
    )


@router.get("/{template_id}/archivo", name="prorrogas_tec.api.templates.file")
def template_file(template_id: int, db: DbSession, user: dict = require_perms("prorrogas_tec", _READ)):
    t = db.get(ProrrogaTemplate, template_id)
    if t is None:
        return _error(404, "plantilla_no_encontrada", "La plantilla no existe.")
    return FileResponse(
        str(TemplateService.abs_path(t.file_path)),
        media_type=DOCX_MIME,
        filename=t.original_name,
    )
