"""
API para generación de documentos PDF/DOCX de tickets Help-Desk.
"""
from flask import request, jsonify, send_file, g
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.models.ticket import Ticket
from itcj.apps.helpdesk.routes.api import documents_api_bp
from itcj.apps.helpdesk.services import document_service
import logging

logger = logging.getLogger(__name__)


@documents_api_bp.post('/generate')
@api_app_required('helpdesk', perms=['helpdesk.documents.api.generate'])
def generate_documents():
    """
    Genera documentos PDF/DOCX a partir de tickets.

    Body:
        {
            "ticket_ids": [1, 2, 3] | "all",
            "doc_type": "solicitud" | "orden_trabajo" | "combinado",
            "format": "pdf" | "docx",
            "output_mode": "zip" | "concatenated"  (solo para múltiples)
        }

    Returns:
        Descarga de archivo (PDF, DOCX o ZIP)
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'invalid_body', 'message': 'Body JSON requerido'}), 400

    ticket_ids = data.get('ticket_ids')
    doc_type = data.get('doc_type')
    doc_format = data.get('format')
    output_mode = data.get('output_mode', 'zip')

    # Validaciones
    if not ticket_ids or not doc_type or not doc_format:
        return jsonify({
            'error': 'missing_fields',
            'message': 'ticket_ids, doc_type y format son requeridos'
        }), 400

    if doc_type not in ('solicitud', 'orden_trabajo', 'combinado'):
        return jsonify({'error': 'invalid_doc_type', 'message': 'doc_type debe ser solicitud, orden_trabajo o combinado'}), 400

    if doc_format not in ('pdf', 'docx'):
        return jsonify({'error': 'invalid_format', 'message': 'format debe ser pdf o docx'}), 400

    if output_mode not in ('zip', 'concatenated'):
        return jsonify({'error': 'invalid_output_mode', 'message': 'output_mode debe ser zip o concatenated'}), 400

    # Obtener tickets
    if ticket_ids == 'all':
        tickets = Ticket.query.order_by(Ticket.created_at.desc()).all()
    elif isinstance(ticket_ids, list):
        tickets = Ticket.query.filter(Ticket.id.in_(ticket_ids)).order_by(Ticket.created_at.desc()).all()
    else:
        return jsonify({'error': 'invalid_ticket_ids', 'message': 'ticket_ids debe ser un array o "all"'}), 400

    if not tickets:
        return jsonify({'error': 'no_tickets_found', 'message': 'No se encontraron tickets'}), 404

    try:
        # Un solo ticket → archivo directo
        if len(tickets) == 1:
            ticket = tickets[0]
            return _generate_single(ticket, doc_type, doc_format)

        # Múltiples tickets
        if output_mode == 'concatenated' and doc_format == 'pdf':
            buffer = document_service.generate_concatenated_pdf(tickets, doc_type)
            prefix = _get_prefix(doc_type)
            return send_file(
                buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'{prefix}_concatenado.pdf',
            )

        # ZIP (default para múltiples, y obligatorio para DOCX múltiple)
        buffer = document_service.generate_batch_zip(tickets, doc_type, doc_format)
        prefix = _get_prefix(doc_type)
        return send_file(
            buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'{prefix}.zip',
        )

    except ValueError as e:
        return jsonify({'error': 'generation_error', 'message': str(e)}), 400
    except Exception as e:
        logger.error(f'Error generando documentos: {e}')
        return jsonify({'error': 'generation_failed', 'message': 'Error interno al generar documentos'}), 500


@documents_api_bp.get('/preview/<int:ticket_id>/<doc_type>')
@api_app_required('helpdesk', perms=['helpdesk.documents.api.generate'])
def preview_document(ticket_id, doc_type):
    """Preview PDF inline para un ticket específico."""
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        return jsonify({'error': 'ticket_not_found'}), 404

    if doc_type not in ('solicitud', 'orden_trabajo', 'combinado'):
        return jsonify({'error': 'invalid_doc_type'}), 400

    try:
        if doc_type == 'solicitud':
            buffer = document_service.generate_solicitud_pdf(ticket)
        elif doc_type == 'combinado':
            buffer = document_service.generate_combined_pdf(ticket)
        else:
            buffer = document_service.generate_orden_trabajo_pdf(ticket)

        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=False,
            download_name=f'{doc_type}_{ticket.ticket_number}.pdf',
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f'Error preview documento: {e}')
        return jsonify({'error': 'Error generando preview'}), 500


def _get_prefix(doc_type: str) -> str:
    """Retorna el prefijo para nombres de archivo."""
    prefixes = {
        'solicitud': 'Solicitudes',
        'orden_trabajo': 'OrdenesTrabajo',
        'combinado': 'Documentos',
    }
    return prefixes.get(doc_type, 'Documentos')


def _generate_single(ticket, doc_type, doc_format):
    """Genera documento(s) para un solo ticket."""

    # Combinado: PDF concatenado o ZIP con ambos DOCX
    if doc_type == 'combinado':
        if doc_format == 'pdf':
            buffer = document_service.generate_combined_pdf(ticket)
            return send_file(
                buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'Combinado_{ticket.ticket_number}.pdf',
            )
        else:
            buffer = document_service.generate_combined_docx_zip(ticket)
            return send_file(
                buffer,
                mimetype='application/zip',
                as_attachment=True,
                download_name=f'Combinado_{ticket.ticket_number}.zip',
            )

    # Solicitud u Orden individual
    generators = {
        ('solicitud', 'pdf'): document_service.generate_solicitud_pdf,
        ('solicitud', 'docx'): document_service.generate_solicitud_docx,
        ('orden_trabajo', 'pdf'): document_service.generate_orden_trabajo_pdf,
        ('orden_trabajo', 'docx'): document_service.generate_orden_trabajo_docx,
    }

    mimetypes = {
        'pdf': 'application/pdf',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    }

    prefix = 'Solicitud' if doc_type == 'solicitud' else 'OrdenTrabajo'
    gen_func = generators[(doc_type, doc_format)]
    buffer = gen_func(ticket)

    return send_file(
        buffer,
        mimetype=mimetypes[doc_format],
        as_attachment=True,
        download_name=f'{prefix}_{ticket.ticket_number}.{doc_format}',
    )
