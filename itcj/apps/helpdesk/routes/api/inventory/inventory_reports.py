"""
API para reportes de inventario con multi-filtros y exportación
"""
from flask import Blueprint, request, jsonify, g, Response
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.services.inventory_reports_service import InventoryReportsService
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

inventory_reports_api_bp = Blueprint('inventory_reports_api', __name__)


@inventory_reports_api_bp.post('/equipment')
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.read.stats'])
def equipment_report():
    """
    Reporte de equipos con multi-filtros.

    Body:
    {
        "department_ids": [1, 2, 3],
        "category_ids": [1, 2],
        "statuses": ["ACTIVE", "MAINTENANCE"],
        "brand": "HP",
        "search": "texto",
        "page": 1,
        "per_page": 50
    }
    """
    try:
        data = request.get_json() or {}
        result = InventoryReportsService.get_equipment_report(data)

        return jsonify({
            'success': True,
            **result
        }), 200

    except Exception as e:
        logger.error(f"Error en reporte de equipos: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@inventory_reports_api_bp.post('/movements')
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.read.stats'])
def movements_report():
    """
    Reporte de movimientos/historial con multi-filtros.

    Body:
    {
        "date_from": "2025-01-01",
        "date_to": "2025-12-31",
        "event_types": ["REGISTERED", "TRANSFERRED"],
        "department_ids": [1, 2],
        "performed_by_id": 5,
        "search": "texto",
        "page": 1,
        "per_page": 50
    }
    """
    try:
        data = request.get_json() or {}
        result = InventoryReportsService.get_movements_report(data)

        return jsonify({
            'success': True,
            **result
        }), 200

    except Exception as e:
        logger.error(f"Error en reporte de movimientos: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@inventory_reports_api_bp.post('/export/csv')
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.read.stats'])
def export_csv():
    """
    Exportar reporte a CSV.

    Body:
    {
        "report_type": "equipment" | "movements" | "warranty" | "maintenance" | "lifecycle",
        "filters": { ... }
    }
    """
    try:
        data = request.get_json() or {}
        report_type = data.get('report_type', 'equipment')
        filters = data.get('filters', {})

        csv_content = ''
        filename = f'reporte_inventario_{report_type}'

        if report_type == 'equipment':
            csv_content = InventoryReportsService.export_equipment_csv(filters)
            filename = 'reporte_equipos'
        elif report_type == 'movements':
            csv_content = InventoryReportsService.export_movements_csv(filters)
            filename = 'reporte_movimientos'
        elif report_type == 'warranty':
            csv_content = InventoryReportsService.export_warranty_csv()
            filename = 'reporte_garantias'
        elif report_type == 'maintenance':
            csv_content = InventoryReportsService.export_maintenance_csv()
            filename = 'reporte_mantenimiento'
        elif report_type == 'lifecycle':
            csv_content = InventoryReportsService.export_lifecycle_csv()
            filename = 'reporte_ciclo_vida'
        else:
            return jsonify({'success': False, 'error': 'Tipo de reporte inválido'}), 400

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'{filename}_{timestamp}.csv'

        # BOM para que Excel abra bien los acentos
        bom = '\ufeff'
        response = Response(
            bom + csv_content,
            mimetype='text/csv; charset=utf-8',
            headers={
                'Content-Disposition': f'attachment; filename={filename}'
            }
        )
        return response

    except Exception as e:
        logger.error(f"Error exportando CSV: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@inventory_reports_api_bp.get('/labels')
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.read.stats'])
def get_labels():
    """Obtiene etiquetas legibles para event_types y statuses."""
    return jsonify({
        'success': True,
        'event_types': InventoryReportsService.get_event_type_labels(),
        'statuses': InventoryReportsService.get_status_labels(),
    }), 200
