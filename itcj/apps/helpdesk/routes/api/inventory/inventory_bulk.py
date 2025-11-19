"""
API para registro masivo de equipos
"""
from flask import Blueprint, request, jsonify, g
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.services.inventory_bulk_service import InventoryBulkService
import logging

logger = logging.getLogger(__name__)

inventory_bulk_api_bp = Blueprint('inventory_bulk_api', __name__)


@inventory_bulk_api_bp.post('/validate-serials')
@api_app_required('helpdesk', perms=['helpdesk.inventory.bulk_create'])
def validate_serial_numbers():
    """
    Valida que los números de serie no estén duplicados.
    Útil para validación previa antes del registro.
    """
    try:
        data = request.get_json()
        
        if not data.get('serial_numbers') or not isinstance(data['serial_numbers'], list):
            return jsonify({'success': False, 'error': 'serial_numbers (array) requerido'}), 400
        
        result = InventoryBulkService.validate_serial_numbers(data['serial_numbers'])
        
        return jsonify({
            'success': True,
            'validation': result
        }), 200
        
    except Exception as e:
        logger.error(f"Error al validar seriales: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@inventory_bulk_api_bp.get('/next-inventory-number/<int:category_id>')
@api_app_required('helpdesk', perms=['helpdesk.inventory.bulk_create'])
def get_next_inventory_number(category_id):
    """Obtiene el siguiente número de inventario para una categoría"""
    try:
        year = request.args.get('year', type=int)
        
        inventory_number = InventoryBulkService.get_next_inventory_number(category_id, year)
        
        return jsonify({
            'success': True,
            'inventory_number': inventory_number
        }), 200
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error al obtener siguiente número: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@inventory_bulk_api_bp.post('/create')
@api_app_required('helpdesk', perms=['helpdesk.inventory.bulk_create'])
def bulk_create_items():
    """
    Crea múltiples equipos con las mismas especificaciones.
    
    Body:
    {
        "category_id": 1,
        "brand": "HP",
        "model": "OptiPlex 7090",
        "specifications": {"processor": "i5", "ram": "16GB"},
        "acquisition_date": "2025-01-15",
        "warranty_expiration": "2027-01-15",
        "maintenance_frequency_days": 180,
        "notes": "Lote enero 2025",
        "items": [
            {
                "serial_number": "SN001",
                "department_id": 5,
                "location_detail": "Salón 203"
            },
            {
                "serial_number": "SN002",
                "department_id": null,  // Va al limbo
            }
        ]
    }
    """
    try:
        data = request.get_json()
        user_id = int(g.current_user['sub'])
        
        # Validaciones básicas
        if not data.get('category_id'):
            return jsonify({'success': False, 'error': 'category_id requerido'}), 400
        
        if not data.get('items') or not isinstance(data['items'], list):
            return jsonify({'success': False, 'error': 'items (array) requerido'}), 400
        
        if len(data['items']) == 0:
            return jsonify({'success': False, 'error': 'Debe incluir al menos un equipo'}), 400
        
        # Validar números de serie únicos
        serial_numbers = [item['serial_number'] for item in data['items']]
        validation = InventoryBulkService.validate_serial_numbers(serial_numbers)
        
        if not validation['valid']:
            return jsonify({
                'success': False,
                'error': 'Números de serie duplicados',
                'validation': validation
            }), 400
        
        # Crear equipos
        created_items = InventoryBulkService.bulk_create_items(data, user_id)
        
        return jsonify({
            'success': True,
            'message': f'{len(created_items)} equipos registrados exitosamente',
            'items': [item.to_dict(include_relations=True) for item in created_items]
        }), 201
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error en registro masivo: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500