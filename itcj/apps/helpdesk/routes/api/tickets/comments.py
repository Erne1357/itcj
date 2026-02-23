"""
Rutas para gestión de comentarios de tickets.
"""
from flask import Blueprint, request, jsonify, g
from werkzeug.utils import secure_filename
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.services import ticket_service
from itcj.apps.helpdesk.services import file_validation_service as fvs
from itcj.apps.helpdesk.models import Attachment
from itcj.core.extensions import db
from itcj.core.services.authz_service import user_roles_in_app
from itcj.config import Config
import os
import logging

logger = logging.getLogger(__name__)

UPLOAD_FOLDER = os.getenv('HELPDESK_UPLOAD_PATH', Config.HELPDESK_UPLOAD_PATH)

# Sub-blueprint para comentarios de tickets
tickets_comments_bp = Blueprint('tickets_comments', __name__)


# ==================== OBTENER COMENTARIOS ====================
@tickets_comments_bp.get('/<int:ticket_id>/comments')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def get_comments(ticket_id):
    """
    Obtiene los comentarios de un ticket.
    Filtra comentarios internos según permisos del usuario.
    
    Returns:
        200: Lista de comentarios
        403: Sin permiso para ver el ticket
        404: Ticket no encontrado
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    try:
        # Verificar que pueda ver el ticket
        ticket = ticket_service.get_ticket_by_id(ticket_id, user_id, check_permissions=True)
        
        # Determinar si puede ver comentarios internos
        can_see_internal = any(role in user_roles for role in ['admin', 'secretary', 'tech_desarrollo', 'tech_soporte'])
        
        # Obtener comentarios
        from itcj.apps.helpdesk.models import Comment
        query = Comment.query.filter_by(ticket_id=ticket_id)
        
        # Filtrar internos si no tiene permiso
        if not can_see_internal:
            query = query.filter_by(is_internal=False)
        
        comments = query.order_by(Comment.created_at.asc()).all()
        
        return jsonify({
            'ticket_id': ticket_id,
            'comments': [comment.to_dict() for comment in comments],
            'count': len(comments)
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener comentarios del ticket {ticket_id}: {e}")
        raise


# ==================== AGREGAR COMENTARIO ====================
@tickets_comments_bp.post('/<int:ticket_id>/comments')
@api_app_required('helpdesk', perms=['helpdesk.comments.api.create'])
def add_comment(ticket_id):
    """
    Agrega un comentario a un ticket.
    
    Body:
        {
            "content": str,  # Contenido del comentario
            "is_internal": bool (opcional, default: false)  # Si es nota interna (solo staff)
        }
    
    Returns:
        201: Comentario creado
        400: Datos inválidos
        403: Sin permiso para comentar o crear notas internas
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')

    # Soportar JSON y FormData (multipart)
    if request.content_type and 'multipart/form-data' in request.content_type:
        content = request.form.get('content', '').strip()
        is_internal = request.form.get('is_internal', 'false').lower() in ('true', '1')
        files = request.files.getlist('files')
    else:
        data = request.get_json() or {}
        content = data.get('content', '').strip()
        is_internal = data.get('is_internal', False)
        files = []

    if not content:
        return jsonify({
            'error': 'missing_content',
            'message': 'Se requiere el contenido del comentario'
        }), 400

    # Validar si puede crear comentarios internos
    if is_internal:
        can_create_internal = any(role in user_roles for role in ['admin', 'secretary', 'tech_desarrollo', 'tech_soporte'])
        if not can_create_internal:
            return jsonify({
                'error': 'forbidden_internal',
                'message': 'No tienes permiso para crear notas internas'
            }), 403

    # Validar límite de archivos
    if len(files) > Config.HELPDESK_MAX_COMMENT_FILES:
        return jsonify({
            'error': 'too_many_files',
            'message': f'Máximo {Config.HELPDESK_MAX_COMMENT_FILES} archivos por comentario'
        }), 400

    # Pre-validar todos los archivos antes de crear el comentario
    allowed_ext = Config.HELPDESK_ALLOWED_EXTENSIONS | Config.HELPDESK_ALLOWED_DOC_EXTENSIONS
    validated_files = []
    for f in files:
        is_valid, result = fvs.validate_and_get_file_info(f, allowed_extensions=allowed_ext)
        if not is_valid:
            return jsonify({'error': 'invalid_file', 'message': f'{f.filename}: {result}'}), 400
        validated_files.append((f, result))

    try:
        # Crear comentario
        comment = ticket_service.add_comment(
            ticket_id=ticket_id,
            author_id=user_id,
            content=content,
            is_internal=is_internal
        )

        # Guardar archivos adjuntos
        ticket = ticket_service.get_ticket_by_id(ticket_id, user_id, check_permissions=False)
        saved_files = []

        for f, info in validated_files:
            try:
                original_filename = secure_filename(f.filename)
                is_img = info['is_image']
                folder = os.path.join(UPLOAD_FOLDER, 'comments', ticket.ticket_number)
                os.makedirs(folder, exist_ok=True)

                if is_img:
                    seq = fvs.get_next_comment_image_number(ticket_id)
                    store_filename = f"{ticket.ticket_number}_{seq}.jpg"
                    filepath = os.path.join(folder, store_filename)
                    compressed, file_size = fvs.compress_image_for_helpdesk(f)
                    with open(filepath, 'wb') as out:
                        out.write(compressed.read())
                    mime_type = 'image/jpeg'
                else:
                    # Documento: nombre original, evitar colisiones
                    store_filename = original_filename
                    counter = 1
                    base, ext = os.path.splitext(store_filename)
                    while os.path.exists(os.path.join(folder, store_filename)):
                        store_filename = f"{base}_{counter}{ext}"
                        counter += 1
                    filepath = os.path.join(folder, store_filename)
                    f.save(filepath)
                    file_size = info['size']
                    mime_type = f.content_type

                att = Attachment(
                    ticket_id=ticket_id,
                    uploaded_by_id=user_id,
                    attachment_type='comment',
                    comment_id=comment.id,
                    filename=store_filename,
                    original_filename=original_filename,
                    filepath=filepath,
                    mime_type=mime_type,
                    file_size=file_size
                )
                db.session.add(att)
                saved_files.append(att)
            except Exception as file_err:
                logger.error(f"Error guardando archivo {f.filename} en comentario: {file_err}")

        if saved_files:
            db.session.commit()

        logger.info(f"Comentario agregado al ticket {ticket_id} por usuario {user_id} ({len(saved_files)} archivos)")

        # Notificar stakeholders
        from itcj.apps.helpdesk.services.notification_helper import HelpdeskNotificationHelper
        from itcj.core.models.user import User
        try:
            author = User.query.get(user_id)
            if author and ticket:
                HelpdeskNotificationHelper.notify_comment_added(ticket, comment, author)
            db.session.commit()
        except Exception as notif_error:
            logger.error(f"Error al enviar notificación de comentario agregado: {notif_error}")

        return jsonify({
            'message': 'Comentario agregado exitosamente',
            'comment': comment.to_dict()
        }), 201

    except Exception as e:
        logger.error(f"Error al agregar comentario al ticket {ticket_id}: {e}")
        raise