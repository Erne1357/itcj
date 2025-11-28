"""
API para gestión de equipos pendientes de asignación
"""
from flask import Blueprint, request, jsonify, g
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.services.inventory_pending_service import InventoryPendingService
import logging

logger = logging.getLogger(__name__)

inventory_pending_api_bp = Blueprint('inventory_pending_api', __name__)


@inventory_pending_api_bp.get('/')
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.read.pending'])
def get_pending_items():
    """Obtiene todos los equipos pendientes de asignación"""
    try:
        category_id = request.args.get('category_id', type=int)
        
        items = InventoryPendingService.get_pending_items(category_id)
        
        return jsonify({
            'success': True,
            'data': [item.to_dict(include_relations=True) for item in items]
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener equipos pendientes: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@inventory_pending_api_bp.get('/stats')
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.read.pending'])
def get_pending_stats():
    """Obtiene estadísticas de equipos pendientes"""
    try:
        stats = InventoryPendingService.get_pending_stats()
        
        return jsonify({
            'success': True,
            'stats': stats
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener estadísticas pendientes: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@inventory_pending_api_bp.post('/assign-to-department')
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.assign.pending'])
def assign_to_department():
    """
    Asigna equipos pendientes a un departamento.
    
    Body:
    {
        "item_ids": [1, 2, 3],
        "department_id": 5,
        "location_detail": "Almacén",
        "notes": "Asignación inicial"
    }
    """
    try:
        data = request.get_json()
        user_id = int(g.current_user['sub'])
        
        # Validaciones
        if not data.get('item_ids') or not isinstance(data['item_ids'], list):
            return jsonify({'success': False, 'error': 'item_ids (array) requerido'}), 400
        
        if not data.get('department_id'):
            return jsonify({'success': False, 'error': 'department_id requerido'}), 400
        
        assigned_items = InventoryPendingService.assign_to_department(
            data['item_ids'],
            data['department_id'],
            user_id,
            data.get('location_detail'),
            data.get('notes')
        )
        
        return jsonify({
            'success': True,
            'message': f'{len(assigned_items)} equipos asignados exitosamente',
            'items': [item.to_dict(include_relations=True) for item in assigned_items]
        }), 200
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error al asignar equipos pendientes: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500