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


@tickets_equipment_bp.get('/equipment/<int:item_id>')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def get_tickets_by_equipment(item_id):
    """
    Obtiene todos los tickets relacionados con un equipo específico.
    
    Params:
        item_id: ID del equipo del inventario
    
    Query params:
        include_closed: bool (default: false) - Incluir tickets cerrados
        limit: int (default: 50) - Límite de resultados
    
    Returns:
        200: Lista de tickets relacionados con el equipo
        403: Sin permiso (solo puede ver tickets de equipos asignados o de su departamento)
        404: Equipo no encontrado
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    try:
        # Obtener el equipo
        from itcj.apps.helpdesk.models import InventoryItem
        item = InventoryItem.query.get(item_id)
        
        if not item or not item.is_active:
            return jsonify({
                'error': 'not_found',
                'message': 'Equipo no encontrado'
            }), 404
        
        # Verificar permisos: 
        # - Admin: ve todos los tickets
        # - Usuario: solo si el equipo está asignado a él o es de su departamento
        # - Técnico: si está asignado al ticket o es del área correspondiente
        from itcj.core.services.authz_service import _get_users_with_position
        secretary_comp_center = _get_users_with_position(['secretary_comp_center'])
        
        if 'admin' not in user_roles and user_id not in secretary_comp_center:
            # Si no es admin ni secretaría, verificar permisos
            if item.assigned_to_user_id == user_id:
                # Es su equipo asignado
                pass
            else:
                # Verificar si es de su departamento
                from itcj.core.services.departments_service import get_user_department
                user_dept = get_user_department(user_id)
                
                if not user_dept or user_dept.id != item.department_id:
                    # No es su equipo ni de su departamento
                    # Verificar si es técnico y tiene tickets asignados de este equipo
                    if 'technician' not in user_roles and 'department_head' not in user_roles:
                        return jsonify({
                            'error': 'forbidden',
                            'message': 'No tienes permiso para ver los tickets de este equipo'
                        }), 403
        
        # Parámetros de consulta
        include_closed = request.args.get('include_closed', 'false').lower() == 'true'
        limit = request.args.get('limit', 50, type=int)
        
        # Obtener tickets relacionados
        from itcj.apps.helpdesk.models import Ticket, TicketInventoryItem
        from itcj.core.extensions import db
        
        query = db.session.query(Ticket).join(
            TicketInventoryItem,
            TicketInventoryItem.ticket_id == Ticket.id
        ).filter(
            TicketInventoryItem.inventory_item_id == item_id
        )
        
        # Filtrar tickets cerrados si no se solicitan
        if not include_closed:
            query = query.filter(
                ~Ticket.status.in_(['CLOSED', 'CANCELED'])
            )
        
        # Aplicar permisos adicionales si no es admin
        if 'admin' not in user_roles and user_id not in secretary_comp_center:
            # Los usuarios normales solo ven:
            # 1. Tickets que ellos crearon
            # 2. Tickets asignados a ellos (técnicos)
            # 3. Tickets de su departamento (jefes de depto)
            
            conditions = [
                Ticket.requester_id == user_id,
                Ticket.assigned_to_user_id == user_id
            ]
            
            # Si es jefe de departamento, agregar condición
            if 'department_head' in user_roles:
                from itcj.core.services.departments_service import get_user_department
                user_dept = get_user_department(user_id)
                if user_dept:
                    conditions.append(Ticket.requester_department_id == user_dept.id)
            
            from sqlalchemy import or_
            query = query.filter(or_(*conditions))
        
        # Ordenar por fecha de creación (más recientes primero)
        query = query.order_by(Ticket.created_at.desc())
        
        # Aplicar límite
        if limit > 0:
            query = query.limit(limit)
        
        tickets = query.all()
        
        # Serializar tickets
        tickets_data = []
        for ticket in tickets:
            ticket_dict = ticket.to_dict(include_relations=True)
            tickets_data.append(ticket_dict)
        
        logger.info(f"Usuario {user_id} consultó {len(tickets_data)} tickets del equipo {item_id}")
        
        return jsonify({
            'item_id': item_id,
            'item': {
                'id': item.id,
                'inventory_number': item.inventory_number,
                'display_name': item.display_name,
                'category': item.category.to_dict() if item.category else None,
                'department': {
                    'id': item.department.id,
                    'name': item.department.name
                } if item.department else None,
                'assigned_to': {
                    'id': item.assigned_to_user.id,
                    'full_name': item.assigned_to_user.full_name
                } if item.assigned_to_user else None
            },
            'tickets': tickets_data,
            'count': len(tickets_data),
            'filters': {
                'include_closed': include_closed,
                'limit': limit
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener tickets del equipo {item_id}: {e}")
        return jsonify({
            'error': 'operation_failed',
            'message': str(e)
        }), 500