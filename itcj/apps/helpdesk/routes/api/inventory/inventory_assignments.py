"""
API para asignación y liberación de equipos
"""
from flask import Blueprint, request, jsonify, g
from itcj.core.extensions import db
from itcj.core.utils.decorators import api_app_required
from itcj.core.services.authz_service import user_roles_in_app
from itcj.apps.helpdesk.models import InventoryItem
from itcj.apps.helpdesk.services.inventory_service import InventoryService
from itcj.apps.helpdesk.utils.inventory_validators import InventoryValidators

bp = Blueprint('inventory_assignments', __name__)


@bp.route('/assign', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.assign'])
def assign_to_user():
    """
    Asignar equipo a un usuario específico
    
    Body:
        - item_id: int (requerido)
        - user_id: int (requerido)
        - location: str (opcional)
        - notes: str (opcional)
    
    Returns:
        200: Equipo asignado
        400: Datos inválidos
        403: Sin permiso
        404: Equipo o usuario no encontrado
    """
    data = request.get_json()
    assigned_by_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(assigned_by_id, 'helpdesk')
    
    # Validaciones básicas
    if not data.get('item_id'):
        return jsonify({'success': False, 'error': 'ID del equipo requerido'}), 400
    
    if not data.get('user_id'):
        return jsonify({'success': False, 'error': 'ID del usuario requerido'}), 400
    
    # Obtener equipo
    item = InventoryItem.query.get(data['item_id'])
    if not item or not item.is_active:
        return jsonify({'success': False, 'error': 'Equipo no encontrado'}), 404
    
    # Verificar permiso: admin o jefe del departamento del equipo
    if 'admin' not in user_roles:
        from itcj.core.services.departments_service import get_user_department
        user_dept = get_user_department(assigned_by_id)
        
        if not user_dept or user_dept.id != item.department_id:
            return jsonify({
                'success': False,
                'error': 'No tiene permiso para asignar equipos de este departamento'
            }), 403
    
    # Validar usuario destino
    is_valid, message, user = InventoryValidators.validate_user_for_assignment(
        data['user_id'],
        item.department_id
    )
    if not is_valid:
        return jsonify({'success': False, 'error': message}), 400
    
    try:
        # Asignar usando el servicio
        updated_item = InventoryService.assign_to_user(
            item_id=data['item_id'],
            user_id=data['user_id'],
            assigned_by_id=assigned_by_id,
            location=data.get('location'),
            notes=data.get('notes'),
            ip_address=request.remote_addr
        )
        
        return jsonify({
            'success': True,
            'message': f'Equipo asignado a {user.full_name}',
            'data': updated_item.to_dict(include_relations=True)
        }), 200
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error: {str(e)}'}), 500


@bp.route('/unassign', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.unassign'])
def unassign_from_user():
    """
    Liberar equipo (volverlo global del departamento)
    
    Body:
        - item_id: int (requerido)
        - notes: str (opcional)
    
    Returns:
        200: Equipo liberado
        400: Datos inválidos o equipo no está asignado
        403: Sin permiso
        404: Equipo no encontrado
    """
    data = request.get_json()
    unassigned_by_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(unassigned_by_id, 'helpdesk')
    
    # Validación
    if not data.get('item_id'):
        return jsonify({'success': False, 'error': 'ID del equipo requerido'}), 400
    
    # Obtener equipo
    item = InventoryItem.query.get(data['item_id'])
    if not item or not item.is_active:
        return jsonify({'success': False, 'error': 'Equipo no encontrado'}), 404
    
    # Verificar que esté asignado
    if not item.is_assigned_to_user:
        return jsonify({
            'success': False,
            'error': 'El equipo no está asignado a ningún usuario'
        }), 400
    
    # Verificar permiso: admin o jefe del departamento del equipo
    if 'admin' not in user_roles:
        from itcj.core.services.departments_service import get_user_department
        user_dept = get_user_department(unassigned_by_id)
        
        if not user_dept or user_dept.id != item.department_id:
            return jsonify({
                'success': False,
                'error': 'No tiene permiso para liberar equipos de este departamento'
            }), 403
    
    try:
        # Liberar usando el servicio
        updated_item = InventoryService.unassign_from_user(
            item_id=data['item_id'],
            unassigned_by_id=unassigned_by_id,
            notes=data.get('notes'),
            ip_address=request.remote_addr
        )
        
        return jsonify({
            'success': True,
            'message': 'Equipo liberado exitosamente',
            'data': updated_item.to_dict(include_relations=True)
        }), 200
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error: {str(e)}'}), 500


@bp.route('/transfer', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.transfer'])
def transfer_between_departments():
    """
    Transferir equipo entre departamentos (SOLO ADMIN)
    
    Body:
        - item_id: int (requerido)
        - new_department_id: int (requerido)
        - notes: str (requerido)
    
    Returns:
        200: Equipo transferido
        400: Datos inválidos o equipo tiene tickets activos
        404: Equipo o departamento no encontrado
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    
    # Validaciones
    if not data.get('item_id'):
        return jsonify({'success': False, 'error': 'ID del equipo requerido'}), 400
    
    if not data.get('new_department_id'):
        return jsonify({'success': False, 'error': 'Departamento destino requerido'}), 400
    
    if not data.get('notes') or len(data['notes'].strip()) < 10:
        return jsonify({
            'success': False,
            'error': 'Debe especificar la razón de la transferencia (mínimo 10 caracteres)'
        }), 400
    
    # Obtener equipo
    item = InventoryItem.query.get(data['item_id'])
    if not item or not item.is_active:
        return jsonify({'success': False, 'error': 'Equipo no encontrado'}), 404
    
    # Validar nuevo departamento
    is_valid, message, new_dept = InventoryValidators.validate_department(
        data['new_department_id']
    )
    if not is_valid:
        return jsonify({'success': False, 'error': message}), 400
    
    # Verificar que sea diferente
    if item.department_id == new_dept.id:
        return jsonify({
            'success': False,
            'error': 'El equipo ya pertenece a ese departamento'
        }), 400
    
    # Verificar que no tenga tickets activos
    if item.active_tickets_count > 0:
        return jsonify({
            'success': False,
            'error': f'No se puede transferir: tiene {item.active_tickets_count} ticket(s) activo(s)'
        }), 400
    
    try:
        # Guardar estado anterior
        old_dept_name = item.department.name if item.department else None
        old_user = None
        
        # Si estaba asignado, liberar
        if item.assigned_to_user_id:
            old_user = item.assigned_to_user.full_name if item.assigned_to_user else None
            item.assigned_to_user_id = None
            item.assigned_by_id = None
            item.assigned_at = None
        
        # Transferir
        item.department_id = new_dept.id
        
        # Registrar en historial
        from itcj.apps.helpdesk.services import InventoryHistoryService
        InventoryHistoryService.log_event(
            item_id=item.id,
            event_type='TRANSFERRED',
            performed_by_id=user_id,
            old_value={
                'department_id': item.department_id,
                'department_name': old_dept_name,
                'assigned_to_user': old_user
            },
            new_value={
                'department_id': new_dept.id,
                'department_name': new_dept.name,
                'assigned_to_user': None
            },
            notes=data['notes'],
            ip_address=request.remote_addr
        )
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Equipo transferido a {new_dept.name}',
            'data': item.to_dict(include_relations=True)
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error: {str(e)}'}), 500


@bp.route('/bulk-assign', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.assign'])
def bulk_assign():
    """
    Asignar múltiples equipos a un usuario
    
    Body:
        - item_ids: list[int] (requerido)
        - user_id: int (requerido)
        - notes: str (opcional)
    
    Returns:
        200: Equipos asignados
        207: Algunos equipos no se pudieron asignar (multistatus)
        400: Datos inválidos
    """
    data = request.get_json()
    assigned_by_id = int(g.current_user['sub'])
    
    # Validaciones
    if not data.get('item_ids') or not isinstance(data['item_ids'], list):
        return jsonify({'success': False, 'error': 'Lista de IDs requerida'}), 400
    
    if not data.get('user_id'):
        return jsonify({'success': False, 'error': 'Usuario destino requerido'}), 400
    
    results = {
        'success': [],
        'failed': []
    }
    
    for item_id in data['item_ids']:
        try:
            item = InventoryItem.query.get(item_id)
            if not item or not item.is_active:
                results['failed'].append({
                    'item_id': item_id,
                    'error': 'Equipo no encontrado'
                })
                continue
            
            # Asignar
            InventoryService.assign_to_user(
                item_id=item_id,
                user_id=data['user_id'],
                assigned_by_id=assigned_by_id,
                notes=data.get('notes'),
                ip_address=request.remote_addr
            )
            
            results['success'].append({
                'item_id': item_id,
                'inventory_number': item.inventory_number
            })
            
        except Exception as e:
            results['failed'].append({
                'item_id': item_id,
                'error': str(e)
            })
    
    status_code = 200 if not results['failed'] else 207
    
    return jsonify({
        'success': len(results['failed']) == 0,
        'message': f"Asignados: {len(results['success'])}, Fallidos: {len(results['failed'])}",
        'data': results
    }), status_code


@bp.route('/update-location', methods=['POST'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.update_location'])
def update_location():
    """
    Actualizar ubicación física de un equipo
    
    Body:
        - item_id: int (requerido)
        - location: str (requerido)
        - notes: str (opcional)
    
    Returns:
        200: Ubicación actualizada
        400: Datos inválidos
        403: Sin permiso
        404: Equipo no encontrado
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    # Validaciones
    if not data.get('item_id'):
        return jsonify({'success': False, 'error': 'ID del equipo requerido'}), 400
    
    if not data.get('location'):
        return jsonify({'success': False, 'error': 'Ubicación requerida'}), 400
    
    # Obtener equipo
    item = InventoryItem.query.get(data['item_id'])
    if not item or not item.is_active:
        return jsonify({'success': False, 'error': 'Equipo no encontrado'}), 404
    
    # Verificar permiso
    if 'admin' not in user_roles:
        from itcj.core.services.departments_service import get_user_department
        user_dept = get_user_department(user_id)
        
        if not user_dept or user_dept.id != item.department_id:
            return jsonify({
                'success': False,
                'error': 'No tiene permiso para actualizar equipos de este departamento'
            }), 403
    
    try:
        # Guardar ubicación anterior
        old_location = item.location_detail
        
        # Actualizar
        item.location_detail = data['location']
        
        # Registrar en historial
        from itcj.apps.helpdesk.services import InventoryHistoryService
        InventoryHistoryService.log_event(
            item_id=item.id,
            event_type='LOCATION_CHANGED',
            performed_by_id=user_id,
            old_value={'location': old_location},
            new_value={'location': data['location']},
            notes=data.get('notes', 'Ubicación actualizada'),
            ip_address=request.remote_addr
        )
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Ubicación actualizada',
            'data': item.to_dict(include_relations=True)
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Error: {str(e)}'}), 500