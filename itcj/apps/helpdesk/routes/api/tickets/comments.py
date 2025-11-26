"""
Rutas para gestión de comentarios de tickets.
"""
from flask import Blueprint, request, jsonify, g
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.services import ticket_service
from itcj.core.services.authz_service import user_roles_in_app
import logging

logger = logging.getLogger(__name__)

# Sub-blueprint para comentarios de tickets
tickets_comments_bp = Blueprint('tickets_comments', __name__)


# ==================== OBTENER COMENTARIOS ====================
@tickets_comments_bp.get('/<int:ticket_id>/comments')
@api_app_required('helpdesk', perms=['helpdesk.tickets.own.read'])
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
@api_app_required('helpdesk', perms=['helpdesk.comments.create'])
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
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    if 'content' not in data:
        return jsonify({
            'error': 'missing_content',
            'message': 'Se requiere el contenido del comentario'
        }), 400
    
    # Validar si puede crear comentarios internos
    is_internal = data.get('is_internal', False)
    if is_internal:
        can_create_internal = any(role in user_roles for role in ['admin', 'secretary', 'tech_desarrollo', 'tech_soporte'])
        if not can_create_internal:
            return jsonify({
                'error': 'forbidden_internal',
                'message': 'No tienes permiso para crear notas internas'
            }), 403
    
    try:
        comment = ticket_service.add_comment(
            ticket_id=ticket_id,
            author_id=user_id,
            content=data['content'],
            is_internal=is_internal
        )
        
        logger.info(f"Comentario agregado al ticket {ticket_id} por usuario {user_id}")

        # Notificar stakeholders sobre el nuevo comentario
        from itcj.apps.helpdesk.services.notification_helper import HelpdeskNotificationHelper
        from itcj.core.models.user import User
        from itcj.core.extensions import db
        try:
            ticket = ticket_service.get_ticket_by_id(ticket_id, user_id, check_permissions=False)
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