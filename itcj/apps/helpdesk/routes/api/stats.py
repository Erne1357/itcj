"""
Rutas para estadísticas y métricas del sistema de tickets.
"""
from flask import Blueprint, jsonify, g
from sqlalchemy import func, case
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.models.ticket import Ticket
from itcj.core.services.authz_service import user_roles_in_app
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

stats_bp = Blueprint('stats', __name__)


@stats_bp.get('/department/<int:department_id>')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def get_department_stats(department_id):
    """
    Obtiene estadísticas agregadas de tickets de un departamento.
    Solo retorna conteos, no los tickets completos.
    
    Args:
        department_id: ID del departamento
    
    Returns:
        200: Estadísticas del departamento
        403: Sin permiso para ver este departamento
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    # Verificar permisos
    from itcj.core.services.authz_service import _get_users_with_position
    secretary_comp_center = _get_users_with_position(['secretary_comp_center'])
    
    can_view = False
    if 'admin' in user_roles or user_id in secretary_comp_center:
        can_view = True
    elif 'department_head' in user_roles:
        # Verificar que sea jefe de este departamento
        from itcj.core.models.position import UserPosition
        user_position = UserPosition.query.filter_by(
            user_id=user_id,
            is_active=True
        ).first()
        
        if user_position and user_position.position:
            can_view = user_position.position.department_id == department_id
    
    if not can_view:
        return jsonify({
            'error': 'forbidden',
            'message': 'No tienes permiso para ver las estadísticas de este departamento'
        }), 403
    
    try:
        # Query base filtrado por departamento
        query = Ticket.query.filter_by(requester_department_id=department_id)
        
        # Conteo de tickets activos
        active_count = query.filter(
            Ticket.status.in_(['PENDING', 'ASSIGNED', 'IN_PROGRESS'])
        ).count()
        
        # Conteo de tickets resueltos
        resolved_count = query.filter(
            Ticket.status.in_(['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED'])
        ).count()
        
        # Tiempo promedio de resolución (en horas)
        resolved_tickets = query.filter(
            Ticket.resolved_at.isnot(None),
            Ticket.created_at.isnot(None)
        ).all()
        
        avg_hours = 0
        if resolved_tickets:
            total_hours = sum(
                (ticket.resolved_at - ticket.created_at).total_seconds() / 3600
                for ticket in resolved_tickets
            )
            avg_hours = round(total_hours / len(resolved_tickets), 1)
        
        # Calcular satisfacción (promedio de rating_attention)
        rated_tickets = query.filter(
            Ticket.rating_attention.isnot(None)
        ).all()
        
        satisfaction_percent = 0
        if rated_tickets:
            avg_rating = sum(t.rating_attention for t in rated_tickets) / len(rated_tickets)
            satisfaction_percent = round((avg_rating / 5) * 100, 1)
        
        # Conteo total
        total_count = query.count()
        
        return jsonify({
            'success': True,
            'data': {
                'department_id': department_id,
                'total_tickets': total_count,
                'active_tickets': active_count,
                'resolved_tickets': resolved_count,
                'avg_resolution_hours': avg_hours,
                'satisfaction_percent': satisfaction_percent,
                'rated_tickets_count': len(rated_tickets)
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener estadísticas del departamento {department_id}: {e}")
        return jsonify({
            'error': 'server_error',
            'message': 'Error al obtener estadísticas'
        }), 500


@stats_bp.get('/technician')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.resolve'])
def get_technician_stats():
    """
    Obtiene estadísticas del técnico actual.
    
    Returns:
        200: Estadísticas del técnico
    """
    user_id = int(g.current_user['sub'])
    
    try:
        # Conteo de tickets asignados (ASSIGNED)
        assigned_count = Ticket.query.filter_by(
            assigned_to_user_id=user_id,
            status='ASSIGNED'
        ).count()
        
        # Conteo de tickets en progreso
        in_progress_count = Ticket.query.filter_by(
            assigned_to_user_id=user_id,
            status='IN_PROGRESS'
        ).count()
        
        # Conteo de tickets resueltos
        resolved_count = Ticket.query.filter_by(
            assigned_to_user_id=user_id
        ).filter(
            Ticket.status.in_(['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED'])
        ).count()
        
        # Tiempo promedio de resolución
        resolved_tickets = Ticket.query.filter_by(
            assigned_to_user_id=user_id
        ).filter(
            Ticket.resolved_at.isnot(None),
            Ticket.created_at.isnot(None)
        ).all()
        
        avg_hours = 0
        if resolved_tickets:
            total_hours = sum(
                (t.resolved_at - t.created_at).total_seconds() / 3600
                for t in resolved_tickets
            )
            avg_hours = round(total_hours / len(resolved_tickets), 1)
        
        # Calcular satisfacción
        rated_tickets = Ticket.query.filter_by(
            assigned_to_user_id=user_id
        ).filter(
            Ticket.rating_attention.isnot(None)
        ).all()
        
        satisfaction_percent = 0
        if rated_tickets:
            avg_rating = sum(t.rating_attention for t in rated_tickets) / len(rated_tickets)
            satisfaction_percent = round((avg_rating / 5) * 100, 1)
        
        # Contar tickets resueltos hoy
        from datetime import datetime, time
        today_start = datetime.combine(datetime.today(), time.min)
        resolved_today_count = Ticket.query.filter_by(
            assigned_to_user_id=user_id
        ).filter(
            Ticket.resolved_at >= today_start,
            Ticket.status.in_(['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED'])
        ).count()
        
        return jsonify({
            'success': True,
            'data': {
                'assigned_count': assigned_count,
                'in_progress_count': in_progress_count,
                'resolved_count': resolved_count,
                'resolved_today_count': resolved_today_count,
                'avg_resolution_hours': avg_hours,
                'satisfaction_percent': satisfaction_percent
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener estadísticas del técnico {user_id}: {e}")
        return jsonify({
            'error': 'server_error',
            'message': 'Error al obtener estadísticas'
        }), 500
