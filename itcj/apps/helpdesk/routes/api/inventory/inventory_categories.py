"""
API para gestión de categorías de inventario
"""
from flask import Blueprint, request, jsonify, g
from itcj.core.extensions import db
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.models import InventoryCategory
from sqlalchemy import func

bp = Blueprint('inventory_categories', __name__)


@bp.route('', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.inventory_categories.api.read'])
def get_categories():
    """
    Obtener todas las categorías de inventario
    
    Query params:
        - active: bool (opcional) - Filtrar por activas/inactivas
        - with_count: bool (opcional) - Incluir conteo de equipos
    
    Returns:
        200: Lista de categorías
    """
    # Filtros
    active_filter = request.args.get('active')
    with_count = request.args.get('with_count', 'false').lower() == 'true'
    
    query = InventoryCategory.query
    
    # Filtro de activos/inactivos
    if active_filter is not None:
        is_active = active_filter.lower() == 'true'
        query = query.filter(InventoryCategory.is_active == is_active)
    
    # Ordenar
    query = query.order_by(InventoryCategory.display_order, InventoryCategory.name)
    
    categories = query.all()
    
    # Serializar
    result = []
    for category in categories:
        data = category.to_dict()
        
        # Si se solicita, agregar conteo de equipos
        if with_count:
            from itcj.apps.helpdesk.models import InventoryItem
            count = db.session.query(func.count(InventoryItem.id)).filter(
                InventoryItem.category_id == category.id,
                InventoryItem.is_active == True
            ).scalar()
            data['items_count'] = count
        
        result.append(data)
    
    return jsonify({
        'success': True,
        'data': result,
        'total': len(result)
    }), 200


@bp.route('/<int:category_id>', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.inventory_categories.api.read'])
def get_category(category_id):
    """
    Obtener una categoría específica
    
    Returns:
        200: Datos de la categoría
        404: Categoría no encontrada
    """
    category = InventoryCategory.query.get(category_id)
    
    if not category:
        return jsonify({
            'success': False,
            'error': 'Categoría no encontrada'
        }), 404
    
    return jsonify({
        'success': True,
        'data': category.to_dict()
    }), 200


@bp.route('', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.inventory_categories.api.update'])
def create_category():
    """
    Crear nueva categoría de inventario
    
    Body:
        - code: str (requerido, único)
        - name: str (requerido)
        - description: str (opcional)
        - icon: str (opcional, default: 'fas fa-box')
        - requires_specs: bool (opcional, default: true)
        - spec_template: dict (opcional)
        - display_order: int (opcional, default: 0)
        - inventory_prefix: str (requerido, 2-10 caracteres)
    
    Returns:
        201: Categoría creada
        400: Datos inválidos
        409: Código ya existe
    """
    data = request.get_json()
    
    # Validaciones
    if not data.get('code'):
        return jsonify({
            'success': False,
            'error': 'El código es requerido'
        }), 400
    
    if not data.get('name'):
        return jsonify({
            'success': False,
            'error': 'El nombre es requerido'
        }), 400
    
    if not data.get('inventory_prefix'):
        return jsonify({
            'success': False,
            'error': 'El prefijo de inventario es requerido'
        }), 400
    
    # Validar longitud del prefijo
    prefix = data['inventory_prefix'].upper().strip()
    if len(prefix) < 2 or len(prefix) > 10:
        return jsonify({
            'success': False,
            'error': 'El prefijo debe tener entre 2 y 10 caracteres'
        }), 400
    
    # Validar código único
    existing = InventoryCategory.query.filter_by(code=data['code']).first()
    if existing:
        return jsonify({
            'success': False,
            'error': f"El código '{data['code']}' ya existe"
        }), 409
    
    # Crear categoría
    category = InventoryCategory(
        code=data['code'],
        name=data['name'],
        description=data.get('description'),
        icon=data.get('icon', 'fas fa-box'),
        is_active=data.get('is_active', True),
        requires_specs=data.get('requires_specs', True),
        spec_template=data.get('spec_template'),
        display_order=data.get('display_order', 0),
        inventory_prefix=prefix
    )
    
    db.session.add(category)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Categoría creada exitosamente',
        'data': category.to_dict()
    }), 201


@bp.route('/<int:category_id>', methods=['PATCH'])
@api_app_required('helpdesk', perms=['helpdesk.inventory_categories.api.update'])
def update_category(category_id):
    """
    Actualizar categoría existente
    
    Body:
        - name: str (opcional)
        - description: str (opcional)
        - icon: str (opcional)
        - requires_specs: bool (opcional)
        - spec_template: dict (opcional)
        - display_order: int (opcional)
        - is_active: bool (opcional)
    
    Nota: El código (code) NO se puede modificar
    
    Returns:
        200: Categoría actualizada
        404: Categoría no encontrada
        400: Datos inválidos
    """
    category = InventoryCategory.query.get(category_id)
    
    if not category:
        return jsonify({
            'success': False,
            'error': 'Categoría no encontrada'
        }), 404
    
    data = request.get_json()
    
    # Campos actualizables
    if 'name' in data:
        category.name = data['name']
    if 'description' in data:
        category.description = data['description']
    if 'icon' in data:
        category.icon = data['icon']
    if 'requires_specs' in data:
        category.requires_specs = data['requires_specs']
    if 'spec_template' in data:
        category.spec_template = data['spec_template']
    if 'display_order' in data:
        category.display_order = data['display_order']
    if 'is_active' in data:
        category.is_active = data['is_active']
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Categoría actualizada exitosamente',
        'data': category.to_dict()
    }), 200


@bp.route('/<int:category_id>/toggle', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.inventory_categories.api.update'])
def toggle_category(category_id):
    """
    Activar/desactivar categoría
    
    Returns:
        200: Estado actualizado
        404: Categoría no encontrada
    """
    category = InventoryCategory.query.get(category_id)
    
    if not category:
        return jsonify({
            'success': False,
            'error': 'Categoría no encontrada'
        }), 404
    
    # Cambiar estado
    category.is_active = not category.is_active
    db.session.commit()
    
    status_text = 'activada' if category.is_active else 'desactivada'
    
    return jsonify({
        'success': True,
        'message': f'Categoría {status_text} exitosamente',
        'data': {
            'id': category.id,
            'is_active': category.is_active
        }
    }), 200


@bp.route('/reorder', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.inventory_categories.api.update'])
def reorder_categories():
    """
    Reordenar categorías (drag & drop)
    
    Body:
        - categories: list[dict]
            - id: int
            - display_order: int
    
    Returns:
        200: Orden actualizado
        400: Datos inválidos
    """
    data = request.get_json()
    
    if not data.get('categories'):
        return jsonify({
            'success': False,
            'error': 'Se requiere el array de categorías'
        }), 400
    
    try:
        for item in data['categories']:
            category = InventoryCategory.query.get(item['id'])
            if category:
                category.display_order = item['display_order']
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Orden actualizado exitosamente'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'Error al reordenar: {str(e)}'
        }), 500