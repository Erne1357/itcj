"""
Documents API v2 — 2 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/documents.py
"""
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.helpdesk.schemas.documents import GenerateDocumentsRequest

router = APIRouter(tags=["helpdesk-documents"])
logger = logging.getLogger(__name__)

_PREFIXES = {"solicitud": "Solicitudes", "orden_trabajo": "OrdenesTrabajo", "combinado": "Documentos"}
_MIMETYPES = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def _stream(buffer, mimetype, filename):
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type=mimetype,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _generate_single(ticket, doc_type, doc_format):
    from itcj2.apps.helpdesk.services import document_service

    if doc_type == "combinado":
        if doc_format == "pdf":
            buffer = document_service.generate_combined_pdf(ticket)
            return _stream(buffer, "application/pdf", f"Combinado_{ticket.ticket_number}.pdf")
        else:
            buffer = document_service.generate_combined_docx_zip(ticket)
            return _stream(buffer, "application/zip", f"Combinado_{ticket.ticket_number}.zip")

    generators = {
        ("solicitud", "pdf"): document_service.generate_solicitud_pdf,
        ("solicitud", "docx"): document_service.generate_solicitud_docx,
        ("orden_trabajo", "pdf"): document_service.generate_orden_trabajo_pdf,
        ("orden_trabajo", "docx"): document_service.generate_orden_trabajo_docx,
    }

    prefix = "Solicitud" if doc_type == "solicitud" else "OrdenTrabajo"
    gen_func = generators[(doc_type, doc_format)]
    buffer = gen_func(ticket)

    return _stream(buffer, _MIMETYPES[doc_format], f"{prefix}_{ticket.ticket_number}.{doc_format}")


@router.post("/generate")
def generate_documents(
    body: GenerateDocumentsRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.documents.api.generate"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.ticket import Ticket
    from itcj2.apps.helpdesk.services import document_service

    if body.doc_type not in ("solicitud", "orden_trabajo", "combinado"):
        raise HTTPException(400, detail={"error": "invalid_doc_type", "message": "doc_type debe ser solicitud, orden_trabajo o combinado"})
    if body.format not in ("pdf", "docx"):
        raise HTTPException(400, detail={"error": "invalid_format", "message": "format debe ser pdf o docx"})
    if body.output_mode not in ("zip", "concatenated"):
        raise HTTPException(400, detail={"error": "invalid_output_mode", "message": "output_mode debe ser zip o concatenated"})

    if body.ticket_ids == "all":
        tickets = Ticket.query.order_by(Ticket.created_at.desc()).all()
    elif isinstance(body.ticket_ids, list):
        tickets = Ticket.query.filter(Ticket.id.in_(body.ticket_ids)).order_by(Ticket.created_at.desc()).all()
    else:
        raise HTTPException(400, detail={"error": "invalid_ticket_ids", "message": 'ticket_ids debe ser un array o "all"'})

    if not tickets:
        raise HTTPException(404, detail={"error": "no_tickets_found", "message": "No se encontraron tickets"})

    try:
        if len(tickets) == 1:
            return _generate_single(tickets[0], body.doc_type, body.format)

        if body.output_mode == "concatenated" and body.format == "pdf":
            buffer = document_service.generate_concatenated_pdf(tickets, body.doc_type)
            prefix = _PREFIXES.get(body.doc_type, "Documentos")
            return _stream(buffer, "application/pdf", f"{prefix}_concatenado.pdf")

        buffer = document_service.generate_batch_zip(tickets, body.doc_type, body.format)
        prefix = _PREFIXES.get(body.doc_type, "Documentos")
        return _stream(buffer, "application/zip", f"{prefix}.zip")

    except ValueError as e:
        raise HTTPException(400, detail={"error": "generation_error", "message": str(e)})
    except Exception as e:
        logger.error(f"Error generando documentos: {e}")
        raise HTTPException(500, detail={"error": "generation_failed", "message": "Error interno al generar documentos"})


@router.get("/preview/{ticket_id}/{doc_type}")
def preview_document(
    ticket_id: int,
    doc_type: str,
    user: dict = require_perms("helpdesk", ["helpdesk.documents.api.generate"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.ticket import Ticket
    from itcj2.apps.helpdesk.services import document_service

    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        raise HTTPException(404, detail={"error": "ticket_not_found"})

    if doc_type not in ("solicitud", "orden_trabajo", "combinado"):
        raise HTTPException(400, detail={"error": "invalid_doc_type"})

    try:
        if doc_type == "solicitud":
            buffer = document_service.generate_solicitud_pdf(ticket)
        elif doc_type == "combinado":
            buffer = document_service.generate_combined_pdf(ticket)
        else:
            buffer = document_service.generate_orden_trabajo_pdf(ticket)

        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{doc_type}_{ticket.ticket_number}.pdf"'},
        )
    except ValueError as e:
        raise HTTPException(400, detail={"error": str(e)})
    except Exception as e:
        logger.error(f"Error preview documento: {e}")
        raise HTTPException(500, detail={"error": "Error generando preview"})
