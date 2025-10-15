from flask import request, jsonify, g
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.services import assignment_service
from itcj.core.services.authz_service import user_roles_in_app
from . import assignments_api_bp
import logging

logger = logging.getLogger(__name__)


# ==================== ASIGNAR TICKET ====================
@assignments_api_bp.post('')
@api_app_required('helpdesk', perms=['helpdesk.assign'])
def assign_ticket():
    """
    Asigna un ticket a un técnico o equipo (secretaría/admin).
    
    Body:
        {
            "ticket_id": int,
            "assigned_to_user_id": int (opcional),  # ID del técnico
            "assigned_to_team": str (opcional),     # 'desarrollo' o 'soporte'
            "reason": str (opcional)                # Razón de la asignación
        }
    
    Nota: Debe proporcionar assigned_to_user_id O assigned_to_team, no ambos.
    
    Returns:
        201: Ticket asignado exitosamente
        400: Datos inválidos
        403: Sin permiso para asignar
        404: Ticket o usuario no encontrado
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    
    # Validar campo requerido
    if 'ticket_id' not in data:
        return jsonify({
            'error': 'missing_ticket_id',
            'message': 'Se requiere el campo ticket_id'
        }), 400
    
    # Validar que tenga al menos uno de los dos
    if not data.get('assigned_to_user_id') and not data.get('assigned_to_team'):
        return jsonify({
            'error': 'missing_assignment_target',
            'message': 'Debe proporcionar assigned_to_user_id o assigned_to_team'
        }), 400
    
    try:
        assignment = assignment_service.assign_ticket(
            ticket_id=data['ticket_id'],
            assigned_by_id=user_id,
            assigned_to_user_id=data.get('assigned_to_user_id'),
            assigned_to_team=data.get('assigned_to_team'),
            reason=data.get('reason')
        )
        
        logger.info(f"Ticket {data['ticket_id']} asignado por usuario {user_id}")
        
        # TODO: Emitir evento SSE
        # from itcj.apps.helpdesk.services.notification_service import notify_ticket_assigned
        # notify_ticket_assigned(assignment)
        
        return jsonify({
            'message': 'Ticket asignado exitosamente',
            'assignment': assignment.to_dict()
        }), 201
        
    except Exception as e:
        logger.error(f"Error al asignar ticket: {e}")
        raise


# ==================== REASIGNAR TICKET ====================
@assignments_api_bp.post('/<int:ticket_id>/reassign')
@api_app_required('helpdesk', perms=['helpdesk.reassign'])
def reassign_ticket(ticket_id):
    """
    Reasigna un ticket que ya estaba asignado.
    
    Body:
        {
            "assigned_to_user_id": int (opcional),  # Nuevo técnico
            "assigned_to_team": str (opcional),     # Nuevo equipo
            "reason": str                           # Razón de la reasignación (recomendado)
        }
    
    Returns:
        200: Ticket reasignado
        400: Datos inválidos
        403: Sin permiso
        404: Ticket no encontrado
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    
    # Validar que tenga al menos uno de los dos
    if not data.get('assigned_to_user_id') and not data.get('assigned_to_team'):
        return jsonify({
            'error': 'missing_assignment_target',
            'message': 'Debe proporcionar assigned_to_user_id o assigned_to_team'
        }), 400
    
    try:
        assignment = assignment_service.reassign_ticket(
            ticket_id=ticket_id,
            reassigned_by_id=user_id,
            assigned_to_user_id=data.get('assigned_to_user_id'),
            assigned_to_team=data.get('assigned_to_team'),
            reason=data.get('reason', 'Ticket reasignado')
        )
        
        logger.info(f"Ticket {ticket_id} reasignado por usuario {user_id}")
        
        # TODO: Emitir evento SSE
        
        return jsonify({
            'message': 'Ticket reasignado exitosamente',
            'assignment': assignment.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Error al reasignar ticket {ticket_id}: {e}")
        raise


# ==================== AUTO-ASIGNARSE TICKET ====================
@assignments_api_bp.post('/<int:ticket_id>/self-assign')
@api_app_required('helpdesk', roles=['tech_desarrollo', 'tech_soporte', 'admin'])
def self_assign_ticket(ticket_id):
    """
    Técnico se auto-asigna un ticket del equipo.
    
    Solo disponible para tickets asignados a un equipo (sin técnico específico).
    
    Returns:
        200: Auto-asignación exitosa
        400: Ticket no disponible para auto-asignación
        403: No perteneces al equipo del ticket
        404: Ticket no encontrado
    """
    user_id = int(g.current_user['sub'])
    
    try:
        assignment = assignment_service.self_assign_ticket(
            ticket_id=ticket_id,
            technician_id=user_id
        )
        
        logger.info(f"Técnico {user_id} se auto-asignó el ticket {ticket_id}")
        
        # TODO: Emitir evento SSE
        
        return jsonify({
            'message': 'Te has asignado el ticket exitosamente',
            'assignment': assignment.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Error al auto-asignarse ticket {ticket_id}: {e}")
        raise


# ==================== HISTORIAL DE ASIGNACIONES ====================
@assignments_api_bp.get('/<int:ticket_id>/history')
@api_app_required('helpdesk', perms=['helpdesk.all.read'])
def get_assignment_history(ticket_id):
    """
    Obtiene el historial completo de asignaciones de un ticket.
    
    Solo disponible para admin y secretaría.
    
    Returns:
        200: Historial de asignaciones
        404: Ticket no encontrado
    """
    try:
        history = assignment_service.get_assignment_history(ticket_id)
        
        return jsonify({
            'ticket_id': ticket_id,
            'history': history
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener historial de asignaciones del ticket {ticket_id}: {e}")
        raise


# ==================== OBTENER TICKETS DEL EQUIPO ====================
@assignments_api_bp.get('/team/<string:team_name>')
@api_app_required('helpdesk', roles=['tech_desarrollo', 'tech_soporte', 'admin'])
def get_team_tickets(team_name):
    """
    Obtiene tickets asignados al equipo (disponibles para auto-asignación).
    
    Params:
        team_name: 'desarrollo' o 'soporte'
    
    Query params:
        - include_details: true/false (default: false) - Incluir detalles completos
    
    Returns:
        200: Lista de tickets del equipo
        400: Nombre de equipo inválido
        403: No perteneces al equipo
    """
    user_id = int(g.current_user['sub'])
    include_details = request.args.get('include_details', 'false').lower() == 'true'
    
    try:
        tickets = assignment_service.get_team_tickets(
            team_name=team_name,
            technician_id=user_id
        )
        
        # Serializar tickets
        tickets_data = []
        for ticket in tickets:
            if include_details:
                tickets_data.append(ticket.to_dict(include_relations=True))
            else:
                # Solo info básica para lista rápida
                tickets_data.append({
                    'id': ticket.id,
                    'ticket_number': ticket.ticket_number,
                    'title': ticket.title,
                    'area': ticket.area,
                    'priority': ticket.priority,
                    'status': ticket.status,
                    'created_at': ticket.created_at.isoformat() if ticket.created_at else None,
                    'requester': {
                        'id': ticket.requester.id,
                        'name': ticket.requester.full_name
                    } if ticket.requester else None
                })
        
        return jsonify({
            'team': team_name,
            'count': len(tickets_data),
            'tickets': tickets_data
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener tickets del equipo {team_name}: {e}")
        raise


# ==================== OBTENER TÉCNICOS DISPONIBLES ====================
@assignments_api_bp.get('/technicians/<string:area>')
@api_app_required('helpdesk', perms=['helpdesk.assign'])
def get_available_technicians(area):
    """
    Obtiene la lista de técnicos disponibles para un área.
    
    Útil para la secretaría al asignar tickets.
    
    Params:
        area: 'DESARROLLO' o 'SOPORTE'
    
    Returns:
        200: Lista de técnicos
        400: Área inválida
    """
    # Validar área
    if area not in ['DESARROLLO', 'SOPORTE']:
        return jsonify({
            'error': 'invalid_area',
            'message': 'El área debe ser DESARROLLO o SOPORTE'
        }), 400
    
    try:
        technicians = assignment_service.get_technicians_by_area(area)
        
        # Serializar técnicos con info básica
        technicians_data = []
        for tech in technicians:
            # Contar tickets activos del técnico
            from itcj.apps.helpdesk.models import Ticket
            active_tickets_count = Ticket.query.filter(
                Ticket.assigned_to_user_id == tech.id,
                Ticket.status.in_(['ASSIGNED', 'IN_PROGRESS'])
            ).count()
            
            technicians_data.append({
                'id': tech.id,
                'name': tech.full_name,
                'username': tech.username,
                'active_tickets': active_tickets_count
            })
        
        # Ordenar por carga de trabajo (menos tickets primero)
        technicians_data.sort(key=lambda x: x['active_tickets'])
        
        return jsonify({
            'area': area,
            'technicians': technicians_data
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener técnicos del área {area}: {e}")
        return jsonify({
            'error': 'fetch_failed',
            'message': str(e)
        }), 500


# ==================== ESTADÍSTICAS DE ASIGNACIÓN ====================
@assignments_api_bp.get('/stats')
@api_app_required('helpdesk', perms=['helpdesk.all.read'])
def get_assignment_stats():
    """
    Obtiene estadísticas de asignación de tickets.
    
    Útil para el dashboard de secretaría.
    
    Returns:
        200: Estadísticas de asignación
    """
    from itcj.apps.helpdesk.models import Ticket
    from itcj.core.extensions import db
    
    try:
        # Tickets sin asignar
        unassigned = Ticket.query.filter_by(status='PENDING').count()
        
        # Tickets asignados a equipos (sin técnico específico)
        team_assigned = Ticket.query.filter(
            Ticket.assigned_to_team.isnot(None),
            Ticket.assigned_to_user_id.is_(None),
            Ticket.status.in_(['ASSIGNED', 'IN_PROGRESS'])
        ).count()
        
        # Tickets en progreso por área
        in_progress_desarrollo = Ticket.query.filter(
            Ticket.area == 'DESARROLLO',
            Ticket.status.in_(['ASSIGNED', 'IN_PROGRESS'])
        ).count()
        
        in_progress_soporte = Ticket.query.filter(
            Ticket.area == 'SOPORTE',
            Ticket.status.in_(['ASSIGNED', 'IN_PROGRESS'])
        ).count()
        
        # Tickets urgentes sin asignar
        urgent_unassigned = Ticket.query.filter(
            Ticket.priority == 'URGENTE',
            Ticket.status == 'PENDING'
        ).count()
        
        return jsonify({
            'unassigned': unassigned,
            'team_assigned': team_assigned,
            'urgent_unassigned': urgent_unassigned,
            'in_progress': {
                'desarrollo': in_progress_desarrollo,
                'soporte': in_progress_soporte
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener estadísticas de asignación: {e}")
        return jsonify({
            'error': 'stats_failed',
            'message': str(e)
        }), 500