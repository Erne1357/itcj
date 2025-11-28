"""
Rutas para gestión de colaboradores en tickets.
"""
from flask import Blueprint, request, jsonify, g
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.services import collaborator_service
from itcj.core.services.authz_service import user_roles_in_app
import logging

logger = logging.getLogger(__name__)

# Sub-blueprint para colaboradores de tickets
tickets_collaborators_bp = Blueprint('tickets_collaborators', __name__)


# ==================== AGREGAR COLABORADOR ====================
@tickets_collaborators_bp.post('/<int:ticket_id>/collaborators')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.resolve'])
def add_collaborator(ticket_id):
    """
    Agrega un colaborador a un ticket.
    
    Body:
        {
            "user_id": int,
            "collaboration_role": str (opcional, se auto-sugiere),
            "time_invested_minutes": int (opcional),
            "notes": str (opcional)
        }
    
    Returns:
        201: Colaborador agregado exitosamente
        400: Datos inválidos
        403: Sin permiso
        404: Ticket o usuario no encontrado
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    
    # Validar datos requeridos
    if 'user_id' not in data:
        return jsonify({
            'error': 'missing_user_id',
            'message': 'Se requiere el campo user_id'
        }), 400
    
    # Validar que tenga permiso para gestionar colaboradores
    if not collaborator_service.can_user_manage_collaborators(user_id, ticket_id):
        return jsonify({
            'error': 'forbidden',
            'message': 'No tienes permiso para gestionar colaboradores de este ticket'
        }), 403
    
    try:
        collaborator = collaborator_service.add_collaborator(
            ticket_id=ticket_id,
            user_id=data['user_id'],
            collaboration_role=data.get('collaboration_role'),
            time_invested_minutes=data.get('time_invested_minutes'),
            notes=data.get('notes'),
            added_by_id=user_id
        )
        
        logger.info(f"Colaborador {data['user_id']} agregado al ticket {ticket_id} por usuario {user_id}")
        
        return jsonify({
            'message': 'Colaborador agregado exitosamente',
            'collaborator': collaborator.to_dict()
        }), 201
        
    except Exception as e:
        logger.error(f"Error al agregar colaborador: {e}")
        raise


# ==================== AGREGAR MÚLTIPLES COLABORADORES ====================
@tickets_collaborators_bp.post('/<int:ticket_id>/collaborators/batch')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.resolve'])
def add_multiple_collaborators(ticket_id):
    """
    Agrega múltiples colaboradores en una sola operación.
    
    Body:
        {
            "collaborators": [
                {
                    "user_id": int,
                    "collaboration_role": str (opcional),
                    "time_invested_minutes": int (opcional),
                    "notes": str (opcional)
                },
                ...
            ]
        }
    
    Returns:
        201: Colaboradores agregados exitosamente
        400: Datos inválidos
        403: Sin permiso
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    
    # Validar datos
    if 'collaborators' not in data or not isinstance(data['collaborators'], list):
        return jsonify({
            'error': 'missing_collaborators',
            'message': 'Se requiere el campo collaborators como array'
        }), 400
    
    if len(data['collaborators']) == 0:
        return jsonify({
            'error': 'empty_collaborators',
            'message': 'La lista de colaboradores está vacía'
        }), 400
    
    # Validar permisos
    if not collaborator_service.can_user_manage_collaborators(user_id, ticket_id):
        return jsonify({
            'error': 'forbidden',
            'message': 'No tienes permiso para gestionar colaboradores de este ticket'
        }), 403
    
    try:
        collaborators = collaborator_service.add_multiple_collaborators(
            ticket_id=ticket_id,
            collaborators_data=data['collaborators'],
            added_by_id=user_id
        )
        
        logger.info(f"{len(collaborators)} colaboradores agregados al ticket {ticket_id}")
        
        return jsonify({
            'message': f'{len(collaborators)} colaboradores agregados exitosamente',
            'collaborators': [c.to_dict() for c in collaborators],
            'count': len(collaborators)
        }), 201
        
    except Exception as e:
        logger.error(f"Error al agregar colaboradores: {e}")
        raise


# ==================== OBTENER COLABORADORES ====================
@tickets_collaborators_bp.get('/<int:ticket_id>/collaborators')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def get_collaborators(ticket_id):
    """
    Obtiene todos los colaboradores de un ticket.
    
    Returns:
        200: Lista de colaboradores
        404: Ticket no encontrado
    """
    user_id = int(g.current_user['sub'])
    
    try:
        # Verificar que el usuario pueda ver el ticket
        from itcj.apps.helpdesk.services.ticket_service import get_ticket_by_id
        ticket = get_ticket_by_id(ticket_id, user_id, check_permissions=True)
        
        # Obtener colaboradores
        collaborators = collaborator_service.get_ticket_collaborators(ticket_id)
        
        return jsonify({
            'ticket_id': ticket_id,
            'collaborators': [c.to_dict() for c in collaborators],
            'count': len(collaborators)
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener colaboradores: {e}")
        raise


# ==================== ACTUALIZAR COLABORADOR ====================
@tickets_collaborators_bp.put('/<int:ticket_id>/collaborators/<int:collab_user_id>')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.resolve'])
def update_collaborator(ticket_id, collab_user_id):
    """
    Actualiza el tiempo invertido y/o notas de un colaborador.
    
    Body:
        {
            "time_invested_minutes": int (opcional),
            "notes": str (opcional)
        }
    
    Returns:
        200: Colaborador actualizado
        400: Datos inválidos
        403: Sin permiso
        404: Colaborador no encontrado
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    
    # Validar que al menos un campo esté presente
    if 'time_invested_minutes' not in data and 'notes' not in data:
        return jsonify({
            'error': 'missing_fields',
            'message': 'Debe proporcionar al menos time_invested_minutes o notes'
        }), 400
    
    # Validar permisos
    if not collaborator_service.can_user_manage_collaborators(user_id, ticket_id):
        return jsonify({
            'error': 'forbidden',
            'message': 'No tienes permiso para modificar colaboradores de este ticket'
        }), 403
    
    try:
        collaborator = collaborator_service.update_collaborator(
            ticket_id=ticket_id,
            user_id=collab_user_id,
            time_invested_minutes=data.get('time_invested_minutes'),
            notes=data.get('notes')
        )
        
        logger.info(f"Colaborador {collab_user_id} actualizado en ticket {ticket_id}")
        
        return jsonify({
            'message': 'Colaborador actualizado exitosamente',
            'collaborator': collaborator.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Error al actualizar colaborador: {e}")
        raise


# ==================== REMOVER COLABORADOR ====================
@tickets_collaborators_bp.delete('/<int:ticket_id>/collaborators/<int:collab_user_id>')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.resolve'])
def remove_collaborator(ticket_id, collab_user_id):
    """
    Remueve un colaborador de un ticket.
    
    Returns:
        200: Colaborador removido
        400: No se puede remover (ej: es el asignado principal)
        403: Sin permiso
        404: Colaborador no encontrado
    """
    user_id = int(g.current_user['sub'])
    
    # Validar permisos
    if not collaborator_service.can_user_manage_collaborators(user_id, ticket_id):
        return jsonify({
            'error': 'forbidden',
            'message': 'No tienes permiso para remover colaboradores de este ticket'
        }), 403
    
    try:
        collaborator_service.remove_collaborator(
            ticket_id=ticket_id,
            user_id=collab_user_id
        )
        
        logger.info(f"Colaborador {collab_user_id} removido del ticket {ticket_id}")
        
        return jsonify({
            'message': 'Colaborador removido exitosamente'
        }), 200
        
    except Exception as e:
        logger.error(f"Error al remover colaborador: {e}")
        raise


# ==================== SUGERIR ROL ====================
@tickets_collaborators_bp.get('/<int:ticket_id>/collaborators/suggest-role/<int:collab_user_id>')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.resolve'])
def suggest_role(ticket_id, collab_user_id):
    """
    Sugiere un rol de colaboración para un usuario en un ticket específico.
    
    Útil para el frontend al agregar colaboradores.
    
    Returns:
        200: Rol sugerido
        404: Ticket o usuario no encontrado
    """
    try:
        suggested_role = collaborator_service.suggest_collaboration_role(
            user_id=collab_user_id,
            ticket_id=ticket_id
        )
        
        return jsonify({
            'ticket_id': ticket_id,
            'user_id': collab_user_id,
            'suggested_role': suggested_role
        }), 200
        
    except Exception as e:
        logger.error(f"Error al sugerir rol: {e}")
        return jsonify({
            'error': 'suggestion_failed',
            'message': str(e)
        }), 500


# ==================== MIS COLABORACIONES ====================
@tickets_collaborators_bp.get('/collaborations/me')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def my_collaborations():
    """
    Obtiene tickets donde el usuario actual colaboró.
    
    Query params:
        - page: Número de página (default: 1)
        - per_page: Items por página (default: 20)
    
    Returns:
        200: Lista de tickets con paginación
    """
    user_id = int(g.current_user['sub'])
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    
    try:
        result = collaborator_service.get_tickets_where_user_collaborated(
            user_id=user_id,
            page=page,
            per_page=per_page
        )
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error al obtener colaboraciones del usuario {user_id}: {e}")
        return jsonify({
            'error': 'fetch_failed',
            'message': str(e)
        }), 500


# ==================== ESTADÍSTICAS DE COLABORACIÓN ====================
@tickets_collaborators_bp.get('/collaborations/me/stats')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def my_collaboration_stats():
    """
    Obtiene estadísticas de colaboración del usuario actual.
    
    Query params:
        - days: Número de días hacia atrás (default: 30)
    
    Returns:
        200: Estadísticas de colaboración
    """
    user_id = int(g.current_user['sub'])
    days = request.args.get('days', 30, type=int)
    
    # Limitar el rango
    days = min(days, 365)
    
    try:
        stats = collaborator_service.get_user_collaboration_stats(
            user_id=user_id,
            days=days
        )
        
        return jsonify(stats), 200
        
    except Exception as e:
        logger.error(f"Error al obtener estadísticas: {e}")
        return jsonify({
            'error': 'stats_failed',
            'message': str(e)
        }), 500