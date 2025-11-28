"""
API para gestión de items del inventario (equipos)
"""
from flask import Blueprint, request, jsonify, g,current_app
from itcj.core.extensions import db
from itcj.core.services.authz_service import user_roles_in_app, _get_users_with_position
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.models import InventoryItem, InventoryCategory
from itcj.apps.helpdesk.services.inventory_service import InventoryService
from itcj.apps.helpdesk.utils.inventory_validators import InventoryValidators
from sqlalchemy import or_, and_, func
from datetime import datetime, date
import logging

bp = Blueprint('inventory_items', __name__)


@bp.route('', methods=['GET'])
@api_app_required('helpdesk')
def get_items():
    """
    Obtener items del inventario con filtros
    
    Query params:
        - category_id: int (opcional)
        - department_id: int (opcional)
        - status: str (opcional)
        - assigned: str (opcional) - 'yes', 'no', 'all'
        - search: str (opcional) - buscar en número, marca, modelo, serie
        - page: int (default: 1)
        - per_page: int (default: 50, max: 100)
    
    Permisos:
        - Admin/Secretaría: Ven todo
        - Jefe Depto: Solo su departamento
        - Usuario: Solo sus equipos asignados
    
    Returns:
        200: Lista de items
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    secretary_comp_center = _get_users_with_position(['secretary_comp_center'])
    user_dept = None

    
    # Query base
    query = InventoryItem.query.filter_by(is_active=True)
    
    # Permisos: restringir por rol
    if 'admin' not in user_roles and user_id not in secretary_comp_center:
        # Jefe de departamento: solo su departamento
        if 'department_head' in user_roles:
            # Obtener departamento del usuario
            from itcj.core.services.departments_service import get_user_department
            user_dept = get_user_department(user_id)
            if user_dept:
                query = query.filter(InventoryItem.department_id == user_dept.id)
            else:
                # Si no tiene departamento, no ve nada
                return jsonify({
                    'success': True,
                    'data': [],
                    'total': 0,
                    'page': 1,
                    'per_page': 50,
                    'total_pages': 0
                }), 200
        else:
            # Usuario normal: solo sus equipos asignados
            department_id = request.args.get('department_id', type=int)
            if department_id:
                query = query.filter(InventoryItem.department_id == department_id)
            else:
                query = query.filter(InventoryItem.assigned_to_user_id == user_id)
    
    # Filtros
    category_id = request.args.get('category_id', type=int)
    if category_id:
        query = query.filter(InventoryItem.category_id == category_id)

    if user_dept is None:
        department_id = request.args.get('department_id', type=int)
        if department_id:
            query = query.filter(InventoryItem.department_id == department_id)

    status = request.args.get('status')
    if status:
        query = query.filter(InventoryItem.status == status.upper())
    
    assigned = request.args.get('assigned')
    if assigned:
        if assigned.lower() == 'yes':
            query = query.filter(InventoryItem.assigned_to_user_id.isnot(None))
        elif assigned.lower() == 'no':
            query = query.filter(InventoryItem.assigned_to_user_id.is_(None))

    department_id = request.args.get('department_id', type=int)
    current_app.logger.warning(f"Department ID filter: {department_id}")
    if department_id:
        query = query.filter(InventoryItem.department_id == department_id)

    # Búsqueda
    search = request.args.get('search')
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                InventoryItem.inventory_number.ilike(search_term),
                InventoryItem.brand.ilike(search_term),
                InventoryItem.model.ilike(search_term),
                InventoryItem.serial_number.ilike(search_term)
            )
        )
    
    # Paginación
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 100)
    
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Serializar con relaciones
    items = [item.to_dict(include_relations=True) for item in paginated.items]
    
    return jsonify({
        'success': True,
        'data': items,
        'total': paginated.total,
        'page': page,
        'per_page': per_page,
        'total_pages': paginated.pages
    }), 200


@bp.route('/<int:item_id>', methods=['GET'])
@api_app_required('helpdesk')
def get_item(item_id):
    """
    Obtener detalle de un item específico
    
    Returns:
        200: Datos del item
        403: Sin permiso
        404: Item no encontrado
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    secretary_comp_center = _get_users_with_position(['secretary_comp_center'])
    
    item = InventoryItem.query.get(item_id)
    
    if not item or not item.is_active:
        return jsonify({
            'success': False,
            'error': 'Equipo no encontrado'
        }), 404
    
    # Verificar permisos
    if 'admin' not in user_roles and user_id not in secretary_comp_center:
        # Jefe de depto: solo su departamento
        if 'department_head' in user_roles:
            from itcj.core.services.departments_service import get_user_department
            user_dept = get_user_department(user_id)
            if not user_dept or item.department_id != user_dept.id:
                return jsonify({
                    'success': False,
                    'error': 'No tiene permiso para ver este equipo'
                }), 403
        else:
            # Usuario: solo su equipo
            if item.assigned_to_user_id != user_id:
                return jsonify({
                    'success': False,
                    'error': 'No tiene permiso para ver este equipo'
                }), 403
    
    return jsonify({
        'success': True,
        'data': item.to_dict(include_relations=True)
    }), 200


@bp.route('', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.create'])
def create_item():
    """
    Registrar nuevo equipo en el inventario
    
    Body:
        - category_id: int (requerido)
        - department_id: int (requerido)
        - brand: str (opcional)
        - model: str (opcional)
        - serial_number: str (opcional, único)
        - specifications: dict (opcional)
        - location_detail: str (opcional)
        - acquisition_date: str ISO (opcional)
        - warranty_expiration: str ISO (opcional)
        - maintenance_frequency_days: int (opcional)
        - notes: str (opcional)
        - assigned_to_user_id: int (opcional)
    
    Returns:
        201: Equipo creado
        400: Datos inválidos
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    
    # Validaciones
    is_valid, message, category = InventoryValidators.validate_category(data.get('category_id'))
    if not is_valid:
        return jsonify({'success': False, 'error': message}), 400
    
    is_valid, message, department = InventoryValidators.validate_department(data.get('department_id'))
    if not is_valid:
        return jsonify({'success': False, 'error': message}), 400
    
    # Validar serial único
    if data.get('serial_number'):
        is_valid, message = InventoryValidators.validate_serial_number(data['serial_number'])
        if not is_valid:
            return jsonify({'success': False, 'error': message}), 400
    
    # Validar especificaciones según template de categoría
    if data.get('specifications'):
        is_valid, message, errors = InventoryValidators.validate_specifications(
            data['specifications'],
            category
        )
        if not is_valid:
            return jsonify({
                'success': False,
                'error': message,
                'validation_errors': errors
            }), 400
    
    # Convertir fechas
    if data.get('acquisition_date'):
        try:
            data['acquisition_date'] = datetime.fromisoformat(data['acquisition_date'].replace('Z', '+00:00')).date()
        except:
            return jsonify({'success': False, 'error': 'Fecha de adquisición inválida'}), 400
    
    if data.get('warranty_expiration'):
        try:
            data['warranty_expiration'] = datetime.fromisoformat(data['warranty_expiration'].replace('Z', '+00:00')).date()
        except:
            return jsonify({'success': False, 'error': 'Fecha de garantía inválida'}), 400
    
    try:
        # Crear equipo usando el servicio
        item = InventoryService.create_item(
            data=data,
            registered_by_id=user_id,
            ip_address=request.remote_addr
        )
        
        return jsonify({
            'success': True,
            'message': 'Equipo registrado exitosamente',
            'data': item.to_dict(include_relations=True)
        }), 201
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error al crear equipo: {str(e)}'}), 500


@bp.route('/<int:item_id>', methods=['PATCH'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.update'])
def update_item(item_id):
    """
    Actualizar información de un equipo
    
    Body:
        - brand: str (opcional)
        - model: str (opcional)
        - specifications: dict (opcional)
        - location_detail: str (opcional)
        - warranty_expiration: str ISO (opcional)
        - maintenance_frequency_days: int (opcional)
        - notes: str (opcional)
    
    Returns:
        200: Equipo actualizado
        404: Equipo no encontrado
        400: Datos inválidos
    """
    user_id = int(g.current_user['sub'])
    
    item = InventoryItem.query.get(item_id)
    if not item or not item.is_active:
        return jsonify({'success': False, 'error': 'Equipo no encontrado'}), 404
    
    data = request.get_json()
    
    # Convertir fecha de garantía si viene
    if data.get('warranty_expiration'):
        try:
            data['warranty_expiration'] = datetime.fromisoformat(data['warranty_expiration'].replace('Z', '+00:00')).date()
        except:
            return jsonify({'success': False, 'error': 'Fecha de garantía inválida'}), 400
    
    try:
        updated_item = InventoryService.update_item(
            item_id=item_id,
            data=data,
            updated_by_id=user_id,
            ip_address=request.remote_addr
        )
        
        return jsonify({
            'success': True,
            'message': 'Equipo actualizado exitosamente',
            'data': updated_item.to_dict(include_relations=True)
        }), 200
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error al actualizar: {str(e)}'}), 500


@bp.route('/<int:item_id>/status', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.update'])
def change_item_status(item_id):
    """
    Cambiar estado de un equipo
    
    Body:
        - status: str (requerido) - ACTIVE, MAINTENANCE, DAMAGED, RETIRED, LOST
        - notes: str (opcional)
    
    Returns:
        200: Estado actualizado
        400: Estado inválido
        404: Equipo no encontrado
    """
    user_id = int(g.current_user['sub'])
    data = request.get_json()
    
    if not data.get('status'):
        return jsonify({'success': False, 'error': 'Estado requerido'}), 400
    
    item = InventoryItem.query.get(item_id)
    if not item or not item.is_active:
        return jsonify({'success': False, 'error': 'Equipo no encontrado'}), 404
    
    # Validar transición de estado
    is_valid, message = InventoryValidators.validate_status_transition(
        item.status,
        data['status']
    )
    if not is_valid:
        return jsonify({'success': False, 'error': message}), 400
    
    try:
        updated_item = InventoryService.change_status(
            item_id=item_id,
            new_status=data['status'],
            changed_by_id=user_id,
            notes=data.get('notes'),
            ip_address=request.remote_addr
        )
        
        return jsonify({
            'success': True,
            'message': f'Estado cambiado a {data["status"]}',
            'data': updated_item.to_dict(include_relations=True)
        }), 200
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error: {str(e)}'}), 500


@bp.route('/<int:item_id>/deactivate', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.delete'])
def deactivate_item(item_id):
    """
    Dar de baja un equipo (soft delete)
    
    Body:
        - reason: str (requerido, mínimo 10 caracteres)
    
    Returns:
        200: Equipo dado de baja
        400: Razón inválida o equipo tiene tickets activos
        404: Equipo no encontrado
    """
    user_id = int(g.current_user['sub'])
    data = request.get_json()
    
    if not data.get('reason') or len(data['reason'].strip()) < 10:
        return jsonify({
            'success': False,
            'error': 'La razón debe tener al menos 10 caracteres'
        }), 400
    
    try:
        item = InventoryService.deactivate_item(
            item_id=item_id,
            deactivated_by_id=user_id,
            reason=data['reason'],
            ip_address=request.remote_addr
        )
        
        return jsonify({
            'success': True,
            'message': 'Equipo dado de baja exitosamente',
            'data': item.to_dict(include_relations=True)
        }), 200
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error: {str(e)}'}), 500


@bp.route('/my-equipment', methods=['GET'])
@api_app_required('helpdesk')
def get_my_equipment():
    """
    Obtener equipos asignados al usuario actual
    
    Query params:
        - category_id: int (opcional)
    
    Returns:
        200: Lista de equipos del usuario
    """
    user_id = int(g.current_user['sub'])
    category_id = request.args.get('category_id', type=int)
    
    items = InventoryService.get_items_for_user(user_id, category_id)
    
    return jsonify({
        'success': True,
        'data': [item.to_dict(include_relations=True) for item in items],
        'total': len(items)
    }), 200


@bp.route('/department/<int:department_id>', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.read.own_dept'])
def get_department_equipment(department_id):
    """
    Obtener equipos de un departamento
    
    Query params:
        - include_assigned: bool (default: true)
    
    Returns:
        200: Lista de equipos del departamento
        403: Sin permiso
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    secretary_comp_center = _get_users_with_position(['secretary_comp_center'])

    
    # Verificar permiso si no es admin
    if 'admin' not in user_roles and user_id not in secretary_comp_center:
        from itcj.core.services.departments_service import get_user_department
        user_dept = get_user_department(user_id)
        if not user_dept or user_dept.id != department_id:
            return jsonify({
                'success': False,
                'error': 'No tiene permiso para ver este departamento'
            }), 403
    
    include_assigned = request.args.get('include_assigned', 'true').lower() == 'true'
    
    items = InventoryService.get_items_for_department(department_id, include_assigned)
    
    return jsonify({
        'success': True,
        'data': [item.to_dict(include_relations=True) for item in items],
        'total': len(items)
    }), 200