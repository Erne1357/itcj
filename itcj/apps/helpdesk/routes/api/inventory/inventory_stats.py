"""
API para estadísticas del inventario
"""
from flask import Blueprint, request, jsonify, g
from itcj.core.services.authz_service import user_roles_in_app, _get_users_with_position
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.services.inventory_stats_service import InventoryStatsService

bp = Blueprint('inventory_stats', __name__)


@bp.route('/overview', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.read.stats'])
def get_overview():
    """
    Obtener estadísticas generales del inventario
    
    Returns:
        200: Estadísticas generales
    """
    stats = InventoryStatsService.get_overview_stats()
    
    return jsonify({
        'success': True,
        'data': stats
    }), 200


@bp.route('/by-category', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.read.stats'])
def get_by_category():
    """
    Obtener estadísticas por categoría
    
    Returns:
        200: Stats por categoría
    """
    stats = InventoryStatsService.get_by_category()
    
    return jsonify({
        'success': True,
        'data': stats,
        'total': len(stats)
    }), 200


@bp.route('/by-department', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.read.stats'])
def get_by_department():
    """
    Obtener estadísticas por departamento
    
    Returns:
        200: Stats por departamento
    """
    stats = InventoryStatsService.get_by_department()
    
    return jsonify({
        'success': True,
        'data': stats,
        'total': len(stats)
    }), 200


@bp.route('/problematic', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.read.stats'])
def get_problematic_items():
    """
    Obtener equipos problemáticos (muchas fallas)
    
    Query params:
        - min_tickets: int (default: 5)
        - days: int (default: 180)
    
    Returns:
        200: Lista de equipos problemáticos
    """
    min_tickets = request.args.get('min_tickets', 5, type=int)
    days = request.args.get('days', 180, type=int)
    
    problematic = InventoryStatsService.get_problematic_items(
        min_tickets=min_tickets,
        days=days
    )
    
    # Serializar items
    result = []
    for data in problematic:
        result.append({
            'item': data['item'].to_dict(include_relations=True),
            'ticket_count': data['ticket_count'],
            'mtbf_days': data['mtbf_days'],
            'recommendation': data['recommendation']
        })
    
    return jsonify({
        'success': True,
        'data': result,
        'total': len(result),
        'filters': {
            'min_tickets': min_tickets,
            'days': days
        }
    }), 200


@bp.route('/warranty', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.read.stats'])
def get_warranty_report():
    """
    Reporte de garantías
    
    Returns:
        200: Estadísticas de garantías
    """
    report = InventoryStatsService.get_warranty_report()
    
    return jsonify({
        'success': True,
        'data': report
    }), 200


@bp.route('/maintenance', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.read.stats'])
def get_maintenance_report():
    """
    Reporte de mantenimientos
    
    Returns:
        200: Estadísticas de mantenimientos
    """
    report = InventoryStatsService.get_maintenance_report()
    
    return jsonify({
        'success': True,
        'data': report
    }), 200


@bp.route('/lifecycle', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.read.stats'])
def get_lifecycle_report():
    """
    Reporte de ciclo de vida (antigüedad de equipos)
    
    Returns:
        200: Estadísticas de ciclo de vida
    """
    report = InventoryStatsService.get_lifecycle_report()
    
    return jsonify({
        'success': True,
        'data': report
    }), 200


@bp.route('/department/<int:department_id>', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.read.own_dept'])
def get_department_stats(department_id):
    """
    Estadísticas de un departamento específico
    
    Returns:
        200: Stats del departamento
        403: Sin permiso
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    secretary_comp_center = _get_users_with_position(['secretary_comp_center'])
    
    # Verificar permiso
    if 'admin' not in user_roles and user_id not in secretary_comp_center:
        from itcj.core.services.departments_service import get_user_department
        user_dept = get_user_department(user_id)
        if not user_dept or user_dept.id != department_id:
            return jsonify({
                'success': False,
                'error': 'No tiene permiso para ver este departamento'
            }), 403
    
    from itcj.apps.helpdesk.models import InventoryItem
    from itcj.core.extensions import db
    from sqlalchemy import func, case
    
    # Total de equipos
    total = InventoryItem.query.filter(
        InventoryItem.department_id == department_id,
        InventoryItem.is_active == True
    ).count()
    
    # Por estado
    by_status = db.session.query(
        InventoryItem.status,
        func.count(InventoryItem.id)
    ).filter(
        InventoryItem.department_id == department_id,
        InventoryItem.is_active == True
    ).group_by(InventoryItem.status).all()
    
    status_counts = {status: count for status, count in by_status}
    
    # Asignación
    assigned = InventoryItem.query.filter(
        InventoryItem.department_id == department_id,
        InventoryItem.is_active == True,
        InventoryItem.assigned_to_user_id.isnot(None)
    ).count()
    
    global_items = InventoryItem.query.filter(
        InventoryItem.department_id == department_id,
        InventoryItem.is_active == True,
        InventoryItem.assigned_to_user_id.is_(None)
    ).count()
    
    # Por categoría
    by_category = db.session.query(
        InventoryItem.category_id,
        func.count(InventoryItem.id)
    ).filter(
        InventoryItem.department_id == department_id,
        InventoryItem.is_active == True
    ).group_by(InventoryItem.category_id).all()
    
    # Obtener nombres de categorías
    from itcj.apps.helpdesk.models import InventoryCategory
    categories_data = []
    for cat_id, count in by_category:
        category = InventoryCategory.query.get(cat_id)
        if category:
            categories_data.append({
                'category_id': cat_id,
                'category_name': category.name,
                'count': count
            })
    
    return jsonify({
        'success': True,
        'data': {
            'department_id': department_id,
            'total': total,
            'by_status': status_counts,
            'assigned': assigned,
            'global': global_items,
            'by_category': categories_data
        }
    }), 200