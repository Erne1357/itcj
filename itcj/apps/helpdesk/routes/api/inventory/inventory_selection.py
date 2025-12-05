"""
API para selección de equipos en tickets (selección múltiple, por grupos, etc.)
"""
from flask import Blueprint, request, jsonify, g
from itcj.core.extensions import db
from itcj.core.utils.decorators import api_app_required
from itcj.core.services.authz_service import user_roles_in_app, _get_users_with_position
from itcj.apps.helpdesk.models import InventoryItem, InventoryGroup, InventoryCategory
from sqlalchemy import and_, or_

bp = Blueprint('inventory_selection', __name__)


@bp.route('/for-ticket', methods=['GET'])
@api_app_required('helpdesk')
def get_items_for_ticket():
    """
    Obtener equipos disponibles para asociar a un ticket.
    Filtra por departamento del usuario y permite búsqueda.
    
    Query params:
        - department_id: int (opcional, si no se pasa usa el del usuario)
        - category_id: int (opcional)
        - group_id: int (opcional)
        - search: str (opcional)
        - include_user_equipment: bool (default: true)
        - include_department_equipment: bool (default: true)
        - include_group_equipment: bool (default: true)
    
    Returns:
        200: Lista de equipos disponibles con información visual
    """
    user_id = int(g.current_user['sub'])
    
    # Determinar departamento
    department_id = request.args.get('department_id', type=int)
    if not department_id:
        # Usar departamento del usuario
        from itcj.core.services.departments_service import get_user_department
        user_dept = get_user_department(user_id)
        if user_dept:
            department_id = user_dept.id
    
    if not department_id:
        return jsonify({
            'success': True,
            'data': []
        }), 200
    
    # Configurar filtros
    category_id = request.args.get('category_id', type=int)
    group_id = request.args.get('group_id', type=int)
    search = request.args.get('search')
    
    include_user = request.args.get('include_user_equipment', 'true').lower() == 'true'
    include_dept = request.args.get('include_department_equipment', 'true').lower() == 'true'
    include_group = request.args.get('include_group_equipment', 'true').lower() == 'true'
    
    # Query base: equipos activos del departamento
    query = InventoryItem.query.filter(
        InventoryItem.department_id == department_id,
        InventoryItem.status == 'ACTIVE',
        InventoryItem.is_active == True
    )
    
    # Filtro de alcance
    scope_filters = []
    if include_user:
        scope_filters.append(InventoryItem.assigned_to_user_id == user_id)
    if include_dept:
        scope_filters.append(and_(
            InventoryItem.assigned_to_user_id.is_(None),
            InventoryItem.group_id.is_(None)
        ))
    if include_group:
        scope_filters.append(InventoryItem.group_id.isnot(None))
    
    if scope_filters:
        query = query.filter(or_(*scope_filters))
    
    # Filtros adicionales
    if category_id:
        query = query.filter(InventoryItem.category_id == category_id)
    
    if group_id:
        query = query.filter(InventoryItem.group_id == group_id)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                InventoryItem.inventory_number.ilike(search_term),
                InventoryItem.brand.ilike(search_term),
                InventoryItem.model.ilike(search_term),
                InventoryItem.location_detail.ilike(search_term)
            )
        )
    
    # Ejecutar y serializar
    items = query.order_by(
        InventoryItem.group_id.asc().nullsfirst(),
        InventoryItem.inventory_number
    ).all()
    
    # Serializar con información visual
    result = []
    for item in items:
        item_data = item.to_dict(include_relations=True)
        
        # Agregar información visual
        item_data['visual'] = {
            'icon': item.category.icon if item.category else 'fas fa-laptop',
            'color': _get_status_color(item.status),
            'badge': _get_item_badge(item)
        }
        
        result.append(item_data)
    
    return jsonify({
        'success': True,
        'data': result,
        'total': len(result)
    }), 200


@bp.route('/by-group/<int:group_id>', methods=['GET'])
@api_app_required('helpdesk')
def get_items_by_group(group_id):
    """
    Obtener todos los equipos de un grupo específico.
    Útil para mostrar ventana de selección de equipos de un salón.
    
    Query params:
        - category_id: int (opcional)
        - status: str (opcional, default: ACTIVE)
    
    Returns:
        200: Lista de equipos del grupo con información visual
        404: Grupo no encontrado
    """
    user_id = int(g.current_user['sub'])
    
    # Verificar que el grupo exista
    group = InventoryGroup.query.get(group_id)
    if not group or not group.is_active:
        return jsonify({
            'success': False,
            'error': 'Grupo no encontrado'
        }), 404
    
    # Verificar permisos: debe ser del mismo departamento
    from itcj.core.services.departments_service import get_user_department
    user_dept = get_user_department(user_id)
    
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    secretary_comp_center = _get_users_with_position(['secretary_comp_center'])
    if 'admin' not in user_roles and user_id not in secretary_comp_center and 'tech_desarrollo' not in user_roles and 'tech_soporte' not in user_roles:
        if not user_dept or user_dept.id != group.department_id:
            return jsonify({
                'success': False,
                'error': 'No tiene permiso para ver este grupo'
            }), 403
    
    # Filtros
    category_id = request.args.get('category_id', type=int)
    status = request.args.get('status', 'ACTIVE')
    
    # Query
    query = InventoryItem.query.filter(
        InventoryItem.group_id == group_id,
        InventoryItem.status == status,
        InventoryItem.is_active == True
    )
    
    if category_id:
        query = query.filter(InventoryItem.category_id == category_id)
    
    items = query.order_by(InventoryItem.inventory_number).all()
    
    # Serializar con información visual agrupada por categoría
    items_by_category = {}
    for item in items:
        cat_id = item.category_id
        if cat_id not in items_by_category:
            items_by_category[cat_id] = {
                'category': item.category.to_dict() if item.category else None,
                'items': []
            }
        
        item_data = item.to_dict(include_relations=True)
        item_data['visual'] = {
            'icon': item.category.icon if item.category else 'fas fa-laptop',
            'color': _get_status_color(item.status),
            'badge': _get_item_badge(item)
        }
        
        items_by_category[cat_id]['items'].append(item_data)
    
    return jsonify({
        'success': True,
        'group': group.to_dict(include_capacities=True),
        'items_by_category': list(items_by_category.values()),
        'total': len(items)
    }), 200


@bp.route('/groups-with-items', methods=['GET'])
@api_app_required('helpdesk')
def get_groups_with_items():
    """
    Obtener grupos del departamento del usuario que tienen equipos.
    Útil para mostrar opciones de selección de grupos en creación de tickets.
    
    Query params:
        - department_id: int (opcional)
        - category_id: int (opcional, filtrar grupos que tengan esta categoría)
    
    Returns:
        200: Lista de grupos con conteo de equipos
    """
    user_id = int(g.current_user['sub'])
    
    # Determinar departamento
    department_id = request.args.get('department_id', type=int)
    if not department_id:
        from itcj.core.services.departments_service import get_user_department
        user_dept = get_user_department(user_id)
        if user_dept:
            department_id = user_dept.id
    
    if not department_id:
        return jsonify({
            'success': True,
            'data': []
        }), 200
    
    category_id = request.args.get('category_id', type=int)
    
    # Obtener grupos del departamento
    query = InventoryGroup.query.filter(
        InventoryGroup.department_id == department_id,
        InventoryGroup.is_active == True
    )
    
    groups = query.order_by(InventoryGroup.name).all()
    
    # Para cada grupo, contar equipos
    result = []
    for group in groups:
        item_query = InventoryItem.query.filter(
            InventoryItem.group_id == group.id,
            InventoryItem.status == 'ACTIVE',
            InventoryItem.is_active == True
        )
        
        if category_id:
            item_query = item_query.filter(InventoryItem.category_id == category_id)
        
        items_count = item_query.count()
        
        if items_count > 0:
            group_data = group.to_dict(include_capacities=False)
            group_data['items_count'] = items_count
            result.append(group_data)
    
    return jsonify({
        'success': True,
        'data': result
    }), 200


@bp.route('/validate-for-ticket', methods=['POST'])
@api_app_required('helpdesk')
def validate_items_for_ticket():
    """
    Validar que los equipos seleccionados sean válidos para un ticket.
    
    Body:
        - item_ids: list[int] (requerido)
    
    Returns:
        200: Validación exitosa con detalles
        400: Items inválidos
    """
    data = request.get_json()
    
    if not data.get('item_ids') or not isinstance(data['item_ids'], list):
        return jsonify({
            'success': False,
            'error': 'item_ids (array) requerido'
        }), 400
    
    # Validar cada item
    items = []
    invalid = []
    departments = set()
    
    for item_id in data['item_ids']:
        item = InventoryItem.query.get(item_id)
        
        if not item or not item.is_active:
            invalid.append({
                'item_id': item_id,
                'reason': 'Equipo no encontrado o inactivo'
            })
            continue
        
        if item.status not in ['ACTIVE', 'MAINTENANCE']:
            invalid.append({
                'item_id': item_id,
                'reason': f'Estado no válido: {item.status}'
            })
            continue
        
        items.append(item.to_dict(include_relations=True))
        departments.add(item.department_id)
    
    # Advertir si son de departamentos diferentes
    multi_dept_warning = None
    if len(departments) > 1:
        multi_dept_warning = 'Los equipos pertenecen a diferentes departamentos'
    
    return jsonify({
        'success': len(invalid) == 0,
        'valid_items': items,
        'invalid_items': invalid,
        'warning': multi_dept_warning,
        'summary': {
            'total_requested': len(data['item_ids']),
            'valid': len(items),
            'invalid': len(invalid)
        }
    }), 200 if len(invalid) == 0 else 400


def _get_status_color(status: str) -> str:
    """Retorna color para el estado del equipo"""
    colors = {
        'ACTIVE': 'success',
        'PENDING_ASSIGNMENT': 'warning',
        'MAINTENANCE': 'info',
        'DAMAGED': 'danger',
        'RETIRED': 'secondary',
        'LOST': 'dark'
    }
    return colors.get(status, 'secondary')


def _get_item_badge(item) -> dict:
    """Retorna badge visual para el equipo"""
    if item.is_assigned_to_user:
        return {
            'text': 'Asignado',
            'color': 'primary'
        }
    elif item.is_in_group:
        return {
            'text': item.group.name if item.group else 'Grupo',
            'color': 'info'
        }
    elif item.is_pending_assignment:
        return {
            'text': 'Pendiente',
            'color': 'warning'
        }
    else:
        return {
            'text': 'Disponible',
            'color': 'success'
        }