from flask import current_app, request, jsonify, g, send_file
from werkzeug.utils import secure_filename
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.services import ticket_service
from itcj.apps.helpdesk.services import file_validation_service as fvs
from itcj.apps.helpdesk.models import Attachment
from itcj.core.extensions import db
from itcj.config import Config
from ...utils.timezone_utils import now_local
from . import attachments_api_bp
import os
import uuid
import logging

logger = logging.getLogger(__name__)

UPLOAD_FOLDER = os.getenv('HELPDESK_UPLOAD_PATH', Config.HELPDESK_UPLOAD_PATH)


def _get_storage_path(ticket, attachment_type, filename_for_doc=None):
    """
    Retorna (folder_path, filename) según el tipo de adjunto.

    - ticket:     uploads/helpdesk/{ticket_id}/{unique}.ext
    - resolution: uploads/helpdesk/resolutions/{ticket_number}/{original_name}
    - comment:    uploads/helpdesk/comments/{ticket_number}/{original_name o consecutive}
    """
    if attachment_type == 'resolution':
        folder = os.path.join(UPLOAD_FOLDER, 'resolutions', ticket.ticket_number)
        return folder, filename_for_doc  # nombre original

    if attachment_type == 'comment':
        folder = os.path.join(UPLOAD_FOLDER, 'comments', ticket.ticket_number)
        return folder, filename_for_doc

    # Default: ticket
    folder = os.path.join(UPLOAD_FOLDER, str(ticket.id))
    unique = f"{ticket.id}_{now_local().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
    return folder, unique


def _build_comment_image_filename(ticket, ticket_id):
    """Genera nombre consecutivo para imagen de comentario: TK-2025-0001_3.jpg"""
    seq = fvs.get_next_comment_image_number(ticket_id)
    return f"{ticket.ticket_number}_{seq}.jpg"


def _ensure_unique_filename(folder, filename):
    """Si el archivo ya existe en la carpeta, agrega sufijo numérico."""
    base, ext = os.path.splitext(filename)
    candidate = filename
    counter = 1
    while os.path.exists(os.path.join(folder, candidate)):
        candidate = f"{base}_{counter}{ext}"
        counter += 1
    return candidate


# ==================== SUBIR ARCHIVO ====================
@attachments_api_bp.post('/ticket/<int:ticket_id>')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def upload_attachment(ticket_id):
    """
    Sube un archivo adjunto a un ticket.

    Form data:
        file: Archivo a subir
        attachment_type: 'ticket' | 'resolution' | 'comment' (default: 'ticket')
        comment_id: ID del comentario (requerido si attachment_type='comment')

    Returns:
        201: Archivo subido exitosamente
        400: Archivo inválido
        403: Sin permiso
        404: Ticket no encontrado
        413: Archivo muy grande
    """
    user_id = int(g.current_user['sub'])
    attachment_type = request.form.get('attachment_type', 'ticket')
    comment_id = request.form.get('comment_id', type=int)

    if attachment_type not in ('ticket', 'resolution', 'comment'):
        return jsonify({'error': 'invalid_type', 'message': 'attachment_type debe ser ticket, resolution o comment'}), 400

    if attachment_type == 'comment' and not comment_id:
        return jsonify({'error': 'missing_comment_id', 'message': 'comment_id es requerido para adjuntos de comentario'}), 400

    if 'file' not in request.files:
        return jsonify({'error': 'no_file', 'message': 'No se proporcionó ningún archivo'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'empty_filename', 'message': 'El archivo no tiene nombre'}), 400

    # Determinar extensiones y tamaño permitido según tipo
    if attachment_type == 'ticket':
        allowed_ext = Config.HELPDESK_ALLOWED_EXTENSIONS
    else:
        allowed_ext = Config.HELPDESK_ALLOWED_EXTENSIONS | Config.HELPDESK_ALLOWED_DOC_EXTENSIONS

    is_valid, result = fvs.validate_and_get_file_info(file, allowed_extensions=allowed_ext)
    if not is_valid:
        return jsonify({'error': 'invalid_file', 'message': result}), 400

    filepath = None
    try:
        ticket = ticket_service.get_ticket_by_id(ticket_id, user_id, check_permissions=True)

        # Verificar límites por tipo
        if attachment_type == 'resolution':
            existing_count = Attachment.query.filter_by(ticket_id=ticket_id, attachment_type='resolution').count()
            if existing_count >= Config.HELPDESK_MAX_RESOLUTION_FILES:
                return jsonify({
                    'error': 'limit_reached',
                    'message': f'Máximo {Config.HELPDESK_MAX_RESOLUTION_FILES} archivos de resolución por ticket'
                }), 400

        elif attachment_type == 'comment' and comment_id:
            existing_count = Attachment.query.filter_by(comment_id=comment_id, attachment_type='comment').count()
            if existing_count >= Config.HELPDESK_MAX_COMMENT_FILES:
                return jsonify({
                    'error': 'limit_reached',
                    'message': f'Máximo {Config.HELPDESK_MAX_COMMENT_FILES} archivos por comentario'
                }), 400

        # Determinar nombre y ruta de almacenamiento
        original_filename = secure_filename(file.filename)
        extension = result['extension']
        is_img = result['is_image']

        if attachment_type == 'comment' and is_img:
            # Imágenes de comentario: nombre consecutivo
            store_filename = _build_comment_image_filename(ticket, ticket_id)
        elif attachment_type in ('resolution', 'comment'):
            # Documentos o imágenes de resolución: nombre original
            store_filename = original_filename
        else:
            store_filename = None  # Se genera en _get_storage_path

        folder, fname = _get_storage_path(ticket, attachment_type, store_filename)

        if attachment_type == 'ticket':
            # Para ticket se genera nombre único
            final_filename = f"{fname}.{extension}"
        else:
            final_filename = _ensure_unique_filename(folder, fname)

        os.makedirs(folder, exist_ok=True)
        filepath = os.path.join(folder, final_filename)

        # Guardar archivo
        mime_type = file.content_type
        file_size = result['size']

        if is_img:
            try:
                compressed, compressed_size = fvs.compress_image_for_helpdesk(file)
                with open(filepath, 'wb') as f:
                    f.write(compressed.read())
                file_size = compressed_size
                mime_type = 'image/jpeg'
            except Exception as e:
                logger.warning(f"No se pudo comprimir imagen, guardando original: {e}")
                file.seek(0)
                file.save(filepath)
        else:
            file.save(filepath)

        # Crear registro en DB
        attachment = Attachment(
            ticket_id=ticket_id,
            uploaded_by_id=user_id,
            attachment_type=attachment_type,
            comment_id=comment_id if attachment_type == 'comment' else None,
            filename=final_filename,
            original_filename=original_filename,
            filepath=filepath,
            mime_type=mime_type,
            file_size=file_size
        )

        db.session.add(attachment)
        db.session.commit()

        logger.info(f"Archivo {original_filename} ({attachment_type}) subido al ticket {ticket_id}")

        return jsonify({
            'message': 'Archivo subido exitosamente',
            'attachment': attachment.to_dict()
        }), 201

    except Exception as e:
        logger.error(f"Error al subir archivo al ticket {ticket_id}: {e}")
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
        raise


# ==================== LISTAR ARCHIVOS ====================
@attachments_api_bp.get('/ticket/<int:ticket_id>')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def list_attachments(ticket_id):
    """
    Lista los archivos adjuntos de un ticket.

    Query params:
        type: Filtrar por tipo ('ticket', 'resolution', 'comment'). Sin filtro = todos.

    Returns:
        200: Lista de archivos
    """
    user_id = int(g.current_user['sub'])

    try:
        ticket = ticket_service.get_ticket_by_id(ticket_id, user_id, check_permissions=True)

        query = Attachment.query.filter_by(ticket_id=ticket_id)

        att_type = request.args.get('type')
        if att_type and att_type in ('ticket', 'resolution', 'comment'):
            query = query.filter_by(attachment_type=att_type)

        attachments = query.order_by(Attachment.uploaded_at.desc()).all()

        return jsonify({
            'ticket_id': ticket_id,
            'count': len(attachments),
            'attachments': [att.to_dict() for att in attachments]
        }), 200

    except Exception as e:
        logger.error(f"Error al listar archivos del ticket {ticket_id}: {e}")
        raise


# ==================== DESCARGAR ARCHIVO ====================
@attachments_api_bp.get('/<int:attachment_id>/download')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def download_attachment(attachment_id):
    """
    Descarga un archivo adjunto.

    Returns:
        200: Archivo descargado
        404: Archivo no encontrado
    """
    user_id = int(g.current_user['sub'])

    try:
        attachment = Attachment.query.get(attachment_id)
        if not attachment:
            return jsonify({'error': 'not_found', 'message': 'Archivo no encontrado'}), 404

        ticket = ticket_service.get_ticket_by_id(attachment.ticket_id, user_id, check_permissions=True)

        if not os.path.exists(attachment.filepath):
            logger.error(f"Archivo físico no encontrado: {attachment.filepath}")
            return jsonify({'error': 'file_not_found', 'message': 'El archivo no existe en el servidor'}), 404

        return send_file(
            attachment.filepath,
            mimetype=attachment.mime_type,
            as_attachment=True,
            download_name=attachment.original_filename
        )

    except Exception as e:
        logger.error(f"Error al descargar archivo {attachment_id}: {e}")
        raise


# ==================== ELIMINAR ARCHIVO ====================
@attachments_api_bp.delete('/<int:attachment_id>')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def delete_attachment(attachment_id):
    """
    Elimina un archivo adjunto (solo el uploader o admin).

    Returns:
        200: Archivo eliminado
        403: Sin permiso
        404: Archivo no encontrado
    """
    user_id = int(g.current_user['sub'])
    from itcj.core.services.authz_service import user_roles_in_app
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    is_admin = 'admin' in user_roles

    try:
        attachment = Attachment.query.get(attachment_id)
        if not attachment:
            return jsonify({'error': 'not_found', 'message': 'Archivo no encontrado'}), 404

        if not is_admin and attachment.uploaded_by_id != user_id:
            return jsonify({'error': 'forbidden', 'message': 'Solo el uploader o admin pueden eliminar el archivo'}), 403

        if os.path.exists(attachment.filepath):
            os.remove(attachment.filepath)
            logger.info(f"Archivo físico eliminado: {attachment.filepath}")

        db.session.delete(attachment)
        db.session.commit()

        logger.info(f"Attachment {attachment_id} eliminado por usuario {user_id}")
        return jsonify({'message': 'Archivo eliminado exitosamente'}), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al eliminar archivo {attachment_id}: {e}")
        return jsonify({'error': 'delete_failed', 'message': str(e)}), 500


# ==================== DESCARGAR ARCHIVO DE CUSTOM FIELD ====================
@attachments_api_bp.get('/custom-field/<int:ticket_id>/<string:field_key>')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def download_custom_field_file(ticket_id, field_key):
    """
    Descarga un archivo de campo personalizado de un ticket.
    """
    user_id = int(g.current_user['sub'])

    try:
        ticket = ticket_service.get_ticket_by_id(ticket_id, user_id, check_permissions=True)

        if not ticket.custom_fields or field_key not in ticket.custom_fields:
            return jsonify({'error': 'field_not_found', 'message': f'El campo "{field_key}" no existe'}), 404

        file_value = ticket.custom_fields[field_key]

        if not isinstance(file_value, str) or not file_value.startswith('/instance/'):
            return jsonify({'error': 'invalid_file_path', 'message': 'El campo no contiene una ruta de archivo válida'}), 404

        relative_path = file_value.lstrip('/')
        filepath = os.path.join(os.getcwd(), relative_path)

        if not os.path.exists(filepath):
            return jsonify({
                'error': 'file_not_found',
                'message': 'El archivo ya no está disponible en el servidor.'
            }), 404

        filename = os.path.basename(filepath)
        ext = filename.rsplit('.', 1)[-1].lower()
        mime_types = {
            'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
            'gif': 'image/gif', 'webp': 'image/webp', 'pdf': 'application/pdf'
        }

        return send_file(
            filepath,
            mimetype=mime_types.get(ext, 'application/octet-stream'),
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        logger.error(f"Error al descargar custom field {field_key} del ticket {ticket_id}: {e}")
        raise
