"""
Rutas para gestión de equipos asociados a tickets.
"""
from flask import Blueprint, request, jsonify, g
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.services import ticket_service
from itcj.core.services.authz_service import user_roles_in_app
import logging

logger = logging.getLogger(__name__)

# Sub-blueprint para equipos de tickets
tickets_equipment_bp = Blueprint('tickets_equipment', __name__)


# ==================== GESTIÓN DE EQUIPOS EN TICKET ====================
@tickets_equipment_bp.post('/<int:ticket_id>/equipment')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def add_equipment_to_ticket(ticket_id):
    """
    Agrega equipos a un ticket existente.
    
    Body:
        {
            "item_ids": [int]  # Array de IDs de equipos a agregar
        }
    
    Returns:
        200: Equipos agregados
        400: Datos inválidos
        403: Sin permiso
        404: Ticket no encontrado
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    
    if not data.get('item_ids') or not isinstance(data['item_ids'], list):
        return jsonify({
            'error': 'missing_item_ids',
            'message': 'Se requiere una lista de IDs de equipos'
        }), 400
    
    try:
        # Verificar permisos sobre el ticket
        ticket = ticket_service.get_ticket_by_id(ticket_id, user_id, check_permissions=True)
        
        # Solo el requester, técnico asignado o admin puede agregar equipos
        user_roles = user_roles_in_app(user_id, 'helpdesk')
        if (ticket.requester_id != user_id and 
            ticket.assigned_to_user_id != user_id and 
            'admin' not in user_roles):
            return jsonify({
                'error': 'forbidden',
                'message': 'No tienes permiso para modificar los equipos de este ticket'
            }), 403
        
        # Agregar equipos
        from itcj.apps.helpdesk.services.ticket_inventory_service import TicketInventoryService
        added = TicketInventoryService.add_items_to_ticket(ticket_id, data['item_ids'])
        
        logger.info(f"{len(added)} equipos agregados al ticket {ticket_id}")
        
        return jsonify({
            'message': f'{len(added)} equipos agregados exitosamente',
            'added_items': [item.to_dict() for item in added]
        }), 200
        
    except ValueError as e:
        return jsonify({
            'error': 'invalid_equipment',
            'message': str(e)
        }), 400
    except Exception as e:
        logger.error(f"Error al agregar equipos al ticket {ticket_id}: {e}")
        return jsonify({
            'error': 'operation_failed',
            'message': str(e)
        }), 500


@tickets_equipment_bp.delete('/<int:ticket_id>/equipment/<int:item_id>')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def remove_equipment_from_ticket(ticket_id, item_id):
    """
    Remueve un equipo de un ticket.
    
    Params:
        ticket_id: ID del ticket
        item_id: ID del equipo a remover
    
    Returns:
        200: Equipo removido
        403: Sin permiso
        404: Ticket o equipo no encontrado
    """
    user_id = int(g.current_user['sub'])
    
    try:
        # Verificar permisos sobre el ticket
        ticket = ticket_service.get_ticket_by_id(ticket_id, user_id, check_permissions=True)
        
        # Solo el requester, técnico asignado o admin pueden remover equipos
        user_roles = user_roles_in_app(user_id, 'helpdesk')
        if (ticket.requester_id != user_id and 
            ticket.assigned_to_user_id != user_id and 
            'admin' not in user_roles):
            return jsonify({
                'error': 'forbidden',
                'message': 'No tienes permiso para modificar los equipos de este ticket'
            }), 403
        
        # Remover equipo
        from itcj.apps.helpdesk.services.ticket_inventory_service import TicketInventoryService
        TicketInventoryService.remove_item_from_ticket(ticket_id, item_id)
        
        logger.info(f"Equipo {item_id} removido del ticket {ticket_id}")
        
        return jsonify({
            'message': 'Equipo removido exitosamente'
        }), 200
        
    except ValueError as e:
        return jsonify({
            'error': 'invalid_operation',
            'message': str(e)
        }), 400
    except Exception as e:
        logger.error(f"Error al remover equipo del ticket {ticket_id}: {e}")
        return jsonify({
            'error': 'operation_failed',
            'message': str(e)
        }), 500


@tickets_equipment_bp.put('/<int:ticket_id>/equipment')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def replace_ticket_equipment(ticket_id):
    """
    Reemplaza todos los equipos de un ticket.
    
    Body:
        {
            "item_ids": [int]  # Nueva lista completa de IDs de equipos
        }
    
    Returns:
        200: Equipos reemplazados
        400: Datos inválidos
        403: Sin permiso
        404: Ticket no encontrado
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    
    if not data.get('item_ids') or not isinstance(data['item_ids'], list):
        return jsonify({
            'error': 'missing_item_ids',
            'message': 'Se requiere una lista de IDs de equipos'
        }), 400
    
    try:
        # Verificar permisos sobre el ticket
        ticket = ticket_service.get_ticket_by_id(ticket_id, user_id, check_permissions=True)
        
        # Solo el requester, técnico asignado o admin pueden reemplazar equipos
        user_roles = user_roles_in_app(user_id, 'helpdesk')
        if (ticket.requester_id != user_id and 
            ticket.assigned_to_user_id != user_id and 
            'admin' not in user_roles):
            return jsonify({
                'error': 'forbidden',
                'message': 'No tienes permiso para modificar los equipos de este ticket'
            }), 403
        
        # Reemplazar equipos
        from itcj.apps.helpdesk.services.ticket_inventory_service import TicketInventoryService
        replaced = TicketInventoryService.replace_ticket_items(ticket_id, data['item_ids'])
        
        logger.info(f"Equipos del ticket {ticket_id} reemplazados: {len(replaced)} nuevos")
        
        return jsonify({
            'message': f'Equipos reemplazados exitosamente: {len(replaced)} nuevos',
            'items': [item.to_dict() for item in replaced]
        }), 200
        
    except ValueError as e:
        return jsonify({
            'error': 'invalid_equipment',
            'message': str(e)
        }), 400
    except Exception as e:
        logger.error(f"Error al reemplazar equipos del ticket {ticket_id}: {e}")
        return jsonify({
            'error': 'operation_failed',
            'message': str(e)
        }), 500


@tickets_equipment_bp.get('/<int:ticket_id>/equipment')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def get_ticket_equipment(ticket_id):
    """
    Obtiene la lista de equipos asociados a un ticket.
    
    Params:
        ticket_id: ID del ticket
    
    Returns:
        200: Lista de equipos
        403: Sin permiso
        404: Ticket no encontrado
    """
    user_id = int(g.current_user['sub'])
    
    try:
        # Verificar permisos sobre el ticket
        ticket = ticket_service.get_ticket_by_id(ticket_id, user_id, check_permissions=True)
        
        # Obtener equipos
        equipment = [item.to_dict(include_relations=True) for item in ticket.inventory_items]
        
        return jsonify({
            'ticket_id': ticket_id,
            'equipment': equipment,
            'count': len(equipment)
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener equipos del ticket {ticket_id}: {e}")
        raise