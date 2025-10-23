"""
API para consultar historial de equipos
"""
from flask import Blueprint, request, jsonify, g
from itcj.core.services.authz_service import user_roles_in_app
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.models import InventoryItem
from itcj.apps.helpdesk.services.inventory_history_service import InventoryHistoryService

bp = Blueprint('inventory_history', __name__)


@bp.route('/item/<int:item_id>', methods=['GET'])
@api_app_required('helpdesk')
def get_item_history(item_id):
    """
    Obtener historial completo de un equipo
    
    Query params:
        - limit: int (opcional, default: 50)
        - event_types: str (opcional, comma-separated)
          Ejemplo: ?event_types=ASSIGNED_TO_USER,REASSIGNED,STATUS_CHANGED
    
    Returns:
        200: Historial del equipo
        403: Sin permiso
        404: Equipo no encontrado
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    # Verificar que el equipo existe
    item = InventoryItem.query.get(item_id)
    if not item:
        return jsonify({'success': False, 'error': 'Equipo no encontrado'}), 404
    
    # Verificar permisos
    if 'admin' not in user_roles and 'helpdesk_secretary' not in user_roles:
        # Jefe de depto: solo su departamento
        if 'department_head' in user_roles:
            from itcj.core.services.departments_service import get_user_department
            user_dept = get_user_department(user_id)
            if not user_dept or item.department_id != user_dept.id:
                return jsonify({
                    'success': False,
                    'error': 'No tiene permiso para ver el historial de este equipo'
                }), 403
        else:
            # Usuario: solo su equipo
            if item.assigned_to_user_id != user_id:
                return jsonify({
                    'success': False,
                    'error': 'No tiene permiso para ver el historial de este equipo'
                }), 403
    
    # Parámetros
    limit = request.args.get('limit', 50, type=int)
    event_types_str = request.args.get('event_types')
    event_types = event_types_str.split(',') if event_types_str else None
    
    # Obtener historial
    history = InventoryHistoryService.get_item_history(
        item_id=item_id,
        limit=limit,
        event_types=event_types
    )
    
    # Serializar con relaciones
    history_data = [h.to_dict(include_relations=True) for h in history]
    
    return jsonify({
        'success': True,
        'data': {
            'item': item.to_dict(include_relations=True),
            'history': history_data,
            'total': len(history_data)
        }
    }), 200


@bp.route('/recent', methods=['GET'])
@api_app_required('helpdesk')
def get_recent_events():
    """
    Obtener eventos recientes del inventario
    
    Query params:
        - department_id: int (opcional)
        - days: int (default: 7)
        - limit: int (default: 50)
    
    Permisos:
        - Admin/Secretaría: Ven todo
        - Jefe Depto: Solo su departamento
    
    Returns:
        200: Eventos recientes
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    department_id = request.args.get('department_id', type=int)
    days = request.args.get('days', 7, type=int)
    limit = request.args.get('limit', 50, type=int)
    
    # Verificar permisos
    if 'admin' not in user_roles and 'helpdesk_secretary' not in user_roles:
        # Jefe de depto: forzar filtro por su departamento
        if 'department_head' in user_roles:
            from itcj.core.services.departments_service import get_user_department
            user_dept = get_user_department(user_id)
            if user_dept:
                department_id = user_dept.id
            else:
                # Sin departamento, no ve nada
                return jsonify({'success': True, 'data': [], 'total': 0}), 200
        else:
            # Usuario regular: no tiene acceso a eventos recientes
            return jsonify({
                'success': False,
                'error': 'No tiene permiso para ver eventos recientes'
            }), 403
    
    # Obtener eventos
    events = InventoryHistoryService.get_recent_events(
        department_id=department_id,
        days=days,
        limit=limit
    )
    
    # Serializar
    events_data = [e.to_dict(include_relations=True) for e in events]
    
    return jsonify({
        'success': True,
        'data': events_data,
        'total': len(events_data),
        'filters': {
            'department_id': department_id,
            'days': days,
            'limit': limit
        }
    }), 200


@bp.route('/user/<int:user_id>', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.view'])
def get_user_assignment_history(user_id):
    """
    Obtener historial de asignaciones de un usuario
    
    Returns:
        200: Historial de asignaciones
        403: Sin permiso
    """
    from itcj.core.models.user import User
    
    # Verificar que el usuario existe
    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'error': 'Usuario no encontrado'}), 404
    
    # Obtener historial
    events = InventoryHistoryService.get_assignment_history(user_id)
    
    # Serializar
    events_data = [e.to_dict(include_relations=True) for e in events]
    
    return jsonify({
        'success': True,
        'data': {
            'user': {
                'id': user.id,
                'full_name': user.full_name,
                'email': user.email
            },
            'history': events_data,
            'total': len(events_data)
        }
    }), 200


@bp.route('/maintenance/<int:item_id>', methods=['GET'])
@api_app_required('helpdesk')
def get_maintenance_history(item_id):
    """
    Obtener historial de mantenimientos de un equipo
    
    Returns:
        200: Historial de mantenimientos
        404: Equipo no encontrado
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    # Verificar equipo
    item = InventoryItem.query.get(item_id)
    if not item:
        return jsonify({'success': False, 'error': 'Equipo no encontrado'}), 404
    
    # Verificar permisos
    if 'admin' not in user_roles and 'helpdesk_secretary' not in user_roles:
        if 'department_head' in user_roles:
            from itcj.core.services.departments_service import get_user_department
            user_dept = get_user_department(user_id)
            if not user_dept or item.department_id != user_dept.id:
                return jsonify({'success': False, 'error': 'Sin permiso'}), 403
        else:
            if item.assigned_to_user_id != user_id:
                return jsonify({'success': False, 'error': 'Sin permiso'}), 403
    
    # Obtener mantenimientos
    maintenance_events = InventoryHistoryService.get_maintenance_history(item_id)
    
    # Serializar
    events_data = [e.to_dict(include_relations=True) for e in maintenance_events]
    
    return jsonify({
        'success': True,
        'data': {
            'item': item.to_dict(include_relations=True),
            'maintenance_history': events_data,
            'total': len(events_data)
        }
    }), 200


@bp.route('/transfers', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.view'])
def get_transfers():
    """
    Obtener transferencias entre departamentos
    
    Query params:
        - days: int (default: 30)
    
    Returns:
        200: Lista de transferencias
    """
    days = request.args.get('days', 30, type=int)
    
    transfers = InventoryHistoryService.get_transfers_between_departments(days)
    
    # Serializar
    transfers_data = [t.to_dict(include_relations=True) for t in transfers]
    
    return jsonify({
        'success': True,
        'data': transfers_data,
        'total': len(transfers_data),
        'filters': {'days': days}
    }), 200