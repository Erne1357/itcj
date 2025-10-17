from flask import request, jsonify, g
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.services import ticket_service
from itcj.apps.helpdesk.models import Comment
from itcj.core.services.authz_service import user_roles_in_app
from itcj.core.extensions import db
from datetime import datetime, timedelta
from ...utils.timezone_utils import now_local
from . import comments_api_bp
import logging

logger = logging.getLogger(__name__)


# ==================== LISTAR COMENTARIOS ====================
@comments_api_bp.get('/ticket/<int:ticket_id>')
@api_app_required('helpdesk', perms=['helpdesk.own.read'])
def get_ticket_comments(ticket_id):
    """
    Obtiene los comentarios de un ticket.
    Filtra comentarios internos según permisos del usuario.
    
    Query params:
        - include_internal: true/false (solo para staff)
    
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
        is_staff = any(role in user_roles for role in ['admin', 'secretary', 'tech_desarrollo', 'tech_soporte'])
        
        # Obtener comentarios
        query = Comment.query.filter_by(ticket_id=ticket_id)
        
        # Filtrar internos si no es staff
        if not is_staff:
            query = query.filter_by(is_internal=False)
        
        comments = query.order_by(Comment.created_at.asc()).all()
        
        return jsonify({
            'ticket_id': ticket_id,
            'count': len(comments),
            'comments': [c.to_dict() for c in comments]
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener comentarios del ticket {ticket_id}: {e}")
        raise


# ==================== AGREGAR COMENTARIO ====================
@comments_api_bp.post('/ticket/<int:ticket_id>')
@api_app_required('helpdesk', perms=['helpdesk.comment'])
def create_comment(ticket_id):
    """
    Agrega un comentario a un ticket.
    
    Body:
        {
            "content": str,  # Contenido del comentario (mínimo 3 caracteres)
            "is_internal": bool (opcional, default: false)  # Nota interna (solo staff)
        }
    
    Returns:
        201: Comentario creado
        400: Datos inválidos
        403: Sin permiso para comentar o crear notas internas
        404: Ticket no encontrado
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    # Validar contenido
    if 'content' not in data or not data['content']:
        return jsonify({
            'error': 'missing_content',
            'message': 'Se requiere el campo content'
        }), 400
    
    content = data['content'].strip()
    if len(content) < 3:
        return jsonify({
            'error': 'content_too_short',
            'message': 'El comentario debe tener al menos 3 caracteres'
        }), 400
    
    # Validar si puede crear comentarios internos
    is_internal = data.get('is_internal', False)
    if is_internal:
        is_staff = any(role in user_roles for role in ['admin', 'secretary', 'tech_desarrollo', 'tech_soporte'])
        if not is_staff:
            return jsonify({
                'error': 'forbidden_internal',
                'message': 'No tienes permiso para crear comentarios internos'
            }), 403
    
    try:
        # Verificar que el usuario pueda comentar en este ticket
        ticket = ticket_service.get_ticket_by_id(ticket_id, user_id, check_permissions=True)
        
        # Validar que no esté cerrado o cancelado (opcional, ajustar según necesidad)
        if ticket.status in ['CLOSED', 'CANCELED']:
            return jsonify({
                'error': 'ticket_closed',
                'message': 'No se pueden agregar comentarios a tickets cerrados o cancelados'
            }), 400
        
        comment = ticket_service.add_comment(
            ticket_id=ticket_id,
            author_id=user_id,
            content=content,
            is_internal=is_internal
        )
        
        logger.info(f"Comentario {'interno' if is_internal else 'público'} agregado al ticket {ticket_id} por usuario {user_id}")
        
        # TODO: Emitir evento SSE
        # from itcj.apps.helpdesk.services.notification_service import notify_comment_added
        # notify_comment_added(ticket, comment)
        
        return jsonify({
            'message': 'Comentario agregado exitosamente',
            'comment': comment.to_dict()
        }), 201
        
    except Exception as e:
        logger.error(f"Error al agregar comentario al ticket {ticket_id}: {e}")
        raise


# ==================== EDITAR COMENTARIO ====================
@comments_api_bp.patch('/<int:comment_id>')
@api_app_required('helpdesk', perms=['helpdesk.comment'])
def update_comment(comment_id):
    """
    Edita un comentario (solo el autor, dentro de 5 minutos).
    
    Body:
        {
            "content": str  # Nuevo contenido
        }
    
    Returns:
        200: Comentario actualizado
        400: Datos inválidos o tiempo expirado
        403: No eres el autor
        404: Comentario no encontrado
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    
    # Validar contenido
    if 'content' not in data or not data['content']:
        return jsonify({
            'error': 'missing_content',
            'message': 'Se requiere el campo content'
        }), 400
    
    content = data['content'].strip()
    if len(content) < 3:
        return jsonify({
            'error': 'content_too_short',
            'message': 'El comentario debe tener al menos 3 caracteres'
        }), 400
    
    try:
        comment = Comment.query.get(comment_id)
        if not comment:
            return jsonify({
                'error': 'not_found',
                'message': 'Comentario no encontrado'
            }), 404
        
        # Verificar que sea el autor
        if comment.author_id != user_id:
            return jsonify({
                'error': 'not_author',
                'message': 'Solo el autor puede editar el comentario'
            }), 403
        
        # Verificar que no hayan pasado más de 5 minutos
        time_limit = timedelta(minutes=5)
        if now_local() - comment.created_at > time_limit:
            return jsonify({
                'error': 'time_expired',
                'message': 'Solo puedes editar comentarios dentro de los primeros 5 minutos'
            }), 400
        
        # Actualizar comentario
        comment.content = content
        comment.updated_at = now_local()
        db.session.commit()
        
        logger.info(f"Comentario {comment_id} editado por usuario {user_id}")
        
        return jsonify({
            'message': 'Comentario actualizado',
            'comment': comment.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al actualizar comentario {comment_id}: {e}")
        return jsonify({
            'error': 'update_failed',
            'message': str(e)
        }), 500


# ==================== ELIMINAR COMENTARIO ====================
@comments_api_bp.delete('/<int:comment_id>')
@api_app_required('helpdesk', perms=['helpdesk.comment'])
def delete_comment(comment_id):
    """
    Elimina un comentario (solo el autor, dentro de 5 minutos, o admin).
    
    Returns:
        200: Comentario eliminado
        400: Tiempo expirado
        403: Sin permiso
        404: Comentario no encontrado
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    is_admin = 'admin' in user_roles
    
    try:
        comment = Comment.query.get(comment_id)
        if not comment:
            return jsonify({
                'error': 'not_found',
                'message': 'Comentario no encontrado'
            }), 404
        
        # Admin puede eliminar siempre
        if not is_admin:
            # Verificar que sea el autor
            if comment.author_id != user_id:
                return jsonify({
                    'error': 'not_author',
                    'message': 'Solo el autor o admin pueden eliminar el comentario'
                }), 403
            
            # Verificar que no hayan pasado más de 5 minutos
            time_limit = timedelta(minutes=5)
            if now_local() - comment.created_at > time_limit:
                return jsonify({
                    'error': 'time_expired',
                    'message': 'Solo puedes eliminar comentarios dentro de los primeros 5 minutos'
                }), 400
        
        ticket_id = comment.ticket_id
        db.session.delete(comment)
        db.session.commit()
        
        logger.info(f"Comentario {comment_id} eliminado por usuario {user_id}")
        
        return jsonify({
            'message': 'Comentario eliminado exitosamente'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al eliminar comentario {comment_id}: {e}")
        return jsonify({
            'error': 'delete_failed',
            'message': str(e)
        }), 500