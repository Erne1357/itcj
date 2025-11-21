"""
API para gestión de grupos de inventario (salones, laboratorios, etc.)
"""
from flask import Blueprint, request, jsonify, g
from itcj.core.services.authz_service import user_roles_in_app
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.services.inventory_group_service import InventoryGroupService
from itcj.apps.helpdesk.models import InventoryGroup, InventoryCategory
from itcj.core.models.department import Department
import logging

logger = logging.getLogger(__name__)

inventory_groups_api_bp = Blueprint('inventory_groups_api', __name__)


@inventory_groups_api_bp.get('/')
@api_app_required('helpdesk', perms=['helpdesk.inventory_groups.view'])
def get_all_groups():
    """Obtiene todos los grupos de inventario (solo admin)"""
    try:
        user_id = int(g.current_user['sub'])
        user_roles = user_roles_in_app(user_id, 'helpdesk')
        
        # Solo admin puede ver todos los grupos sin restricción
        if 'admin' not in user_roles:
            return jsonify({
                'success': False,
                'error': 'No tiene permisos para ver todos los grupos'
            }), 403
        
        include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'
        department_id = request.args.get('department_id', type=int)
        
        query = InventoryGroup.query
        
        if not include_inactive:
            query = query.filter_by(is_active=True)
        
        if department_id is not None:
            query = query.filter_by(department_id=department_id)
        
        groups = query.order_by(InventoryGroup.name).all()
        
        return jsonify({
            'success': True,
            'data': [g.to_dict(include_capacities=True) for g in groups]
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener grupos: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@inventory_groups_api_bp.get('/department/<int:department_id>')
@api_app_required('helpdesk', perms=['helpdesk.inventory_groups.view_own_dept'])
def get_groups_by_department(department_id):
    """Obtiene grupos de un departamento específico"""
    try:
        user_id = int(g.current_user['sub'])
        user_roles = user_roles_in_app(user_id, 'helpdesk')
        
        # Validar acceso: solo puede ver su departamento a menos que sea admin
        if 'admin' not in user_roles:
            # Si no es admin, validar que sea su departamento
            from itcj.core.services.departments_service import get_user_department
            user_dept = get_user_department(user_id)
            
            if not user_dept or user_dept.id != department_id:
                return jsonify({
                    'success': False, 
                    'error': 'No tiene permisos para ver grupos de este departamento'
                }), 403
        
        groups = InventoryGroupService.get_groups_by_department(department_id)
        
        return jsonify({
            'success': True,
            'data': [g.to_dict(include_capacities=True) for g in groups]
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener grupos por departamento: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@inventory_groups_api_bp.get('/<int:group_id>')
@api_app_required('helpdesk', perms=['helpdesk.inventory_groups.view_own_dept'])
def get_group_detail(group_id):
    """Obtiene detalle completo de un grupo"""
    try:
        group = InventoryGroup.query.get(group_id)
        
        if not group:
            return jsonify({'success': False, 'error': 'Grupo no encontrado'}), 404
        
        include_items = request.args.get('include_items', 'false').lower() == 'true'
        
        return jsonify({
            'success': True,
            'data': group.to_dict(include_items=include_items, include_capacities=True)
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener detalle de grupo: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@inventory_groups_api_bp.get('/<int:group_id>/items')
@api_app_required('helpdesk', perms=['helpdesk.inventory_groups.view_own_dept'])
def get_group_items(group_id):
    """Obtiene los equipos asignados a un grupo"""
    try:
        category_id = request.args.get('category_id', type=int)
        
        items = InventoryGroupService.get_group_items(group_id, category_id)
        
        return jsonify({
            'success': True,
            'data': [item.to_dict(include_relations=True) for item in items]
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener items del grupo: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@inventory_groups_api_bp.post('/')
@api_app_required('helpdesk', perms=['helpdesk.inventory_groups.create'])
def create_group():
    """Crea un nuevo grupo"""
    try:
        data = request.get_json()
        user_id = int(g.current_user['sub'])
        
        # Validaciones
        if not data.get('name'):
            return jsonify({'success': False, 'error': 'Nombre requerido'}), 400
        
        if not data.get('department_id'):
            return jsonify({'success': False, 'error': 'Departamento requerido'}), 400
        
        group = InventoryGroupService.create_group(data, user_id)
        
        return jsonify({
            'success': True,
            'message': 'Grupo creado exitosamente',
            'data': group.to_dict(include_capacities=True)
        }), 201
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error al crear grupo: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@inventory_groups_api_bp.put('/<int:group_id>')
@api_app_required('helpdesk', perms=['helpdesk.inventory_groups.edit'])
def update_group(group_id):
    """Actualiza información de un grupo"""
    try:
        data = request.get_json()
        
        group = InventoryGroupService.update_group(group_id, data)
        
        return jsonify({
            'success': True,
            'message': 'Grupo actualizado exitosamente',
            'data': group.to_dict(include_capacities=True)
        }), 200
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error al actualizar grupo: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@inventory_groups_api_bp.put('/<int:group_id>/capacities')
@api_app_required('helpdesk', perms=['helpdesk.inventory_groups.manage_capacity'])
def update_capacities(group_id):
    """Actualiza las capacidades de un grupo"""
    try:
        data = request.get_json()
        
        if 'capacities' not in data:
            return jsonify({'success': False, 'error': 'Capacidades requeridas'}), 400
        
        group = InventoryGroupService.update_capacities(group_id, data['capacities'])
        
        return jsonify({
            'success': True,
            'message': 'Capacidades actualizadas exitosamente',
            'data': group.to_dict(include_capacities=True)
        }), 200
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error al actualizar capacidades: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@inventory_groups_api_bp.delete('/<int:group_id>')
@api_app_required('helpdesk', perms=['helpdesk.inventory_groups.delete'])
def delete_group(group_id):
    """Elimina un grupo (solo si está vacío)"""
    try:
        InventoryGroupService.delete_group(group_id)
        
        return jsonify({
            'success': True,
            'message': 'Grupo eliminado exitosamente'
        }), 200
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error al eliminar grupo: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@inventory_groups_api_bp.post('/<int:group_id>/assign-item')
@api_app_required('helpdesk', perms=['helpdesk.inventory_groups.assign_items'])
def assign_item_to_group(group_id):
    """Asigna un equipo a un grupo"""
    try:
        data = request.get_json()
        user_id = int(g.current_user['sub'])
        
        if not data.get('item_id'):
            return jsonify({'success': False, 'error': 'item_id requerido'}), 400
        
        item = InventoryGroupService.assign_item_to_group(
            data['item_id'],
            group_id,
            user_id
        )
        
        return jsonify({
            'success': True,
            'message': 'Equipo asignado al grupo exitosamente',
            'data': item.to_dict(include_relations=True)
        }), 200
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error al asignar equipo a grupo: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@inventory_groups_api_bp.post('/unassign-item/<int:item_id>')
@api_app_required('helpdesk', perms=['helpdesk.inventory_groups.assign_items'])
def unassign_item_from_group(item_id):
    """Remueve un equipo de su grupo"""
    try:
        user_id = int(g.current_user['sub'])
        
        item = InventoryGroupService.unassign_item_from_group(item_id, user_id)
        
        return jsonify({
            'success': True,
            'message': 'Equipo removido del grupo exitosamente',
            'data': item.to_dict(include_relations=True)
        }), 200
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error al desasignar equipo de grupo: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@inventory_groups_api_bp.post('/<int:group_id>/bulk-assign')
@api_app_required('helpdesk', perms=['helpdesk.inventory_groups.assign_items'])
def bulk_assign_items_to_group(group_id):
    """Asigna múltiples equipos a un grupo de una vez"""
    try:
        data = request.get_json()
        user_id = int(g.current_user['sub'])
        
        if not data.get('item_ids') or not isinstance(data['item_ids'], list):
            return jsonify({'success': False, 'error': 'item_ids (array) requerido'}), 400
        
        assigned = []
        errors = []
        
        for item_id in data['item_ids']:
            try:
                item = InventoryGroupService.assign_item_to_group(item_id, group_id, user_id)
                assigned.append(item.to_dict())
            except Exception as e:
                errors.append({'item_id': item_id, 'error': str(e)})
        
        return jsonify({
            'success': len(errors) == 0,
            'message': f'{len(assigned)} equipos asignados, {len(errors)} errores',
            'assigned': assigned,
            'errors': errors
        }), 200 if len(errors) == 0 else 207
        
    except Exception as e:
        logger.error(f"Error en asignación masiva a grupo: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500