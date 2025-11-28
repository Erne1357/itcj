"""
API para widgets del dashboard de inventario
"""
from flask import Blueprint, request, jsonify, g
from itcj.core.services.authz_service import user_roles_in_app
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.services.inventory_stats_service import InventoryStatsService
from itcj.apps.helpdesk.models import InventoryItem
from itcj.core.extensions import db
from sqlalchemy import func
from datetime import date, timedelta

bp = Blueprint('inventory_dashboard', __name__)


@bp.route('/widgets/quick-stats', methods=['GET'])
@api_app_required('helpdesk')
def get_quick_stats():
    """
    Estadísticas rápidas para cards del dashboard
    
    Returns:
        200: Stats rápidas
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    # Si es admin o secretaría: stats globales
    if 'admin' in user_roles or 'helpdesk_secretary' in user_roles:
        stats = InventoryStatsService.get_overview_stats()
        
        return jsonify({
            'success': True,
            'data': {
                'total_items': stats['total'],
                'active': stats['by_status'].get('ACTIVE', 0),
                'in_maintenance': stats['by_status'].get('MAINTENANCE', 0),
                'damaged': stats['by_status'].get('DAMAGED', 0),
                'assigned_to_users': stats['assigned_to_users'],
                'warranty_expiring_soon': stats['warranty_expiring_soon'],
                'needs_maintenance': stats['needs_maintenance']
            }
        }), 200
    
    # Jefe de departamento: stats de su departamento
    elif 'department_head' in user_roles:
        from itcj.core.services.departments_service import get_user_department
        user_dept = get_user_department(user_id)
        
        if not user_dept:
            return jsonify({
                'success': True,
                'data': {
                    'total_items': 0,
                    'active': 0,
                    'assigned_to_users': 0,
                    'global': 0
                }
            }), 200
        
        total = InventoryItem.query.filter(
            InventoryItem.department_id == user_dept.id,
            InventoryItem.is_active == True
        ).count()
        
        active = InventoryItem.query.filter(
            InventoryItem.department_id == user_dept.id,
            InventoryItem.is_active == True,
            InventoryItem.status == 'ACTIVE'
        ).count()
        
        assigned = InventoryItem.query.filter(
            InventoryItem.department_id == user_dept.id,
            InventoryItem.is_active == True,
            InventoryItem.assigned_to_user_id.isnot(None)
        ).count()
        
        global_items = InventoryItem.query.filter(
            InventoryItem.department_id == user_dept.id,
            InventoryItem.is_active == True,
            InventoryItem.assigned_to_user_id.is_(None)
        ).count()
        
        return jsonify({
            'success': True,
            'data': {
                'department': user_dept.name,
                'total_items': total,
                'active': active,
                'assigned_to_users': assigned,
                'global': global_items
            }
        }), 200
    
    # Usuario regular: sus equipos
    else:
        my_items = InventoryItem.query.filter(
            InventoryItem.assigned_to_user_id == user_id,
            InventoryItem.is_active == True
        ).count()
        
        return jsonify({
            'success': True,
            'data': {
                'my_items': my_items
            }
        }), 200


@bp.route('/widgets/alerts', methods=['GET'])
@api_app_required('helpdesk', perms=['helpdesk.inventory.api.read.stats'])
def get_alerts():
    """
    Alertas del inventario (garantías, mantenimiento, etc.)
    
    Returns:
        200: Lista de alertas
    """
    alerts = []
    
    # Garantías por vencer en 30 días
    warranty_expiring = InventoryItem.query.filter(
        InventoryItem.is_active == True,
        InventoryItem.warranty_expiration >= date.today(),
        InventoryItem.warranty_expiration <= date.today() + timedelta(days=30)
    ).count()
    
    if warranty_expiring > 0:
        alerts.append({
            'type': 'warning',
            'icon': 'fas fa-shield-alt',
            'title': 'Garantías por vencer',
            'message': f'{warranty_expiring} equipo(s) con garantía venciendo en 30 días',
            'action': '/inventory/stats/warranty',
            'priority': 'medium'
        })
    
    # Mantenimiento vencido
    maintenance_overdue = InventoryItem.query.filter(
        InventoryItem.is_active == True,
        InventoryItem.next_maintenance_date.isnot(None),
        InventoryItem.next_maintenance_date < date.today()
    ).count()
    
    if maintenance_overdue > 0:
        alerts.append({
            'type': 'danger',
            'icon': 'fas fa-tools',
            'title': 'Mantenimiento vencido',
            'message': f'{maintenance_overdue} equipo(s) requieren mantenimiento',
            'action': '/inventory/stats/maintenance',
            'priority': 'high'
        })
    
    # Equipos en estado DAMAGED
    damaged = InventoryItem.query.filter(
        InventoryItem.is_active == True,
        InventoryItem.status == 'DAMAGED'
    ).count()
    
    if damaged > 0:
        alerts.append({
            'type': 'danger',
            'icon': 'fas fa-exclamation-triangle',
            'title': 'Equipos dañados',
            'message': f'{damaged} equipo(s) en estado dañado',
            'action': '/inventory/items?status=DAMAGED',
            'priority': 'high'
        })
    
    # Equipos problemáticos (>10 tickets en 6 meses)
    six_months_ago = date.today() - timedelta(days=180)
    from itcj.apps.helpdesk.models import Ticket, TicketInventoryItem

    problematic = db.session.query(
        InventoryItem.id
    ).join(
        TicketInventoryItem, TicketInventoryItem.inventory_item_id == InventoryItem.id
    ).join(
        Ticket, Ticket.id == TicketInventoryItem.ticket_id
    ).filter(
        InventoryItem.is_active == True,
        Ticket.created_at >= six_months_ago
    ).group_by(
        InventoryItem.id
    ).having(
        func.count(Ticket.id) >= 10
    ).count()
    
    if problematic > 0:
        alerts.append({
            'type': 'warning',
            'icon': 'fas fa-chart-line',
            'title': 'Equipos problemáticos',
            'message': f'{problematic} equipo(s) con múltiples fallas',
            'action': '/inventory/stats/problematic',
            'priority': 'medium'
        })
    
    # Ordenar por prioridad
    priority_order = {'high': 0, 'medium': 1, 'low': 2}
    alerts.sort(key=lambda x: priority_order.get(x['priority'], 3))
    
    return jsonify({
        'success': True,
        'data': alerts,
        'total': len(alerts)
    }), 200


@bp.route('/widgets/recent-activity', methods=['GET'])
@api_app_required('helpdesk')
def get_recent_activity():
    """
    Actividad reciente del inventario (últimos eventos)
    
    Query params:
        - limit: int (default: 10)
    
    Returns:
        200: Lista de eventos recientes
    """
    from itcj.apps.helpdesk.services.inventory_history_service import InventoryHistoryService
    
    limit = request.args.get('limit', 10, type=int)
    
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    department_id = None
    
    # Si es jefe de depto, filtrar por su departamento
    if 'admin' not in user_roles and 'helpdesk_secretary' not in user_roles:
        if 'department_head' in user_roles:
            from itcj.core.services.departments_service import get_user_department
            user_dept = get_user_department(user_id)
            if user_dept:
                department_id = user_dept.id
    
    events = InventoryHistoryService.get_recent_events(
        department_id=department_id,
        days=7,
        limit=limit
    )
    
    # Serializar
    events_data = []
    for event in events:
        events_data.append({
            'id': event.id,
            'event_type': event.event_type,
            'event_description': event.get_event_description(event.event_type),
            'item': {
                'id': event.item.id,
                'inventory_number': event.item.inventory_number,
                'display_name': event.item.display_name
            } if event.item else None,
            'performed_by': {
                'id': event.performed_by.id,
                'full_name': event.performed_by.full_name
            } if event.performed_by else None,
            'timestamp': event.timestamp.isoformat() if event.timestamp else None,
            'notes': event.notes
        })
    
    return jsonify({
        'success': True,
        'data': events_data,
        'total': len(events_data)
    }), 200


@bp.route('/widgets/category-chart', methods=['GET'])
@api_app_required('helpdesk')
def get_category_chart():
    """
    Datos para gráfica de equipos por categoría
    
    Returns:
        200: Datos para Chart.js
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    # Admin/Secretaría: todas las categorías
    if 'admin' in user_roles or 'helpdesk_secretary' in user_roles:
        stats = InventoryStatsService.get_by_category()
    else:
        # Jefe de depto: solo su departamento
        from itcj.core.services.departments_service import get_user_department
        user_dept = get_user_department(user_id)
        
        if not user_dept:
            return jsonify({
                'success': True,
                'data': {'labels': [], 'datasets': []}
            }), 200
        
        from itcj.apps.helpdesk.models import InventoryCategory
        
        results = db.session.query(
            InventoryCategory.name,
            func.count(InventoryItem.id)
        ).outerjoin(
            InventoryItem,
            db.and_(
                InventoryItem.category_id == InventoryCategory.id,
                InventoryItem.department_id == user_dept.id,
                InventoryItem.is_active == True
            )
        ).filter(
            InventoryCategory.is_active == True
        ).group_by(InventoryCategory.name).all()
        
        stats = [
            {'category_name': name, 'count': count}
            for name, count in results if count > 0
        ]
    
    # Formatear para Chart.js
    labels = [s['category_name'] for s in stats]
    data = [s['count'] for s in stats]
    
    return jsonify({
        'success': True,
        'data': {
            'labels': labels,
            'datasets': [{
                'label': 'Equipos',
                'data': data,
                'backgroundColor': [
                    '#4e73df', '#1cc88a', '#36b9cc', '#f6c23e',
                    '#e74a3b', '#858796', '#5a5c69', '#2e59d9'
                ]
            }]
        }
    }), 200


@bp.route('/widgets/status-chart', methods=['GET'])
@api_app_required('helpdesk')
def get_status_chart():
    """
    Datos para gráfica de equipos por estado
    
    Returns:
        200: Datos para Chart.js (pie chart)
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    query = InventoryItem.query.filter(InventoryItem.is_active == True)
    
    # Filtrar por departamento si no es admin
    if 'admin' not in user_roles and 'helpdesk_secretary' not in user_roles:
        from itcj.core.services.departments_service import get_user_department
        user_dept = get_user_department(user_id)
        if user_dept:
            query = query.filter(InventoryItem.department_id == user_dept.id)
    
    # Agrupar por estado
    results = db.session.query(
        InventoryItem.status,
        func.count(InventoryItem.id)
    ).filter(
        InventoryItem.is_active == True
    ).group_by(InventoryItem.status).all()
    
    status_labels = {
        'ACTIVE': 'Activo',
        'MAINTENANCE': 'Mantenimiento',
        'DAMAGED': 'Dañado',
        'LOST': 'Extraviado'
    }
    
    status_colors = {
        'ACTIVE': '#1cc88a',
        'MAINTENANCE': '#f6c23e',
        'DAMAGED': '#e74a3b',
        'LOST': '#858796'
    }
    
    labels = [status_labels.get(status, status) for status, _ in results]
    data = [count for _, count in results]
    colors = [status_colors.get(status, '#858796') for status, _ in results]
    
    return jsonify({
        'success': True,
        'data': {
            'labels': labels,
            'datasets': [{
                'data': data,
                'backgroundColor': colors
            }]
        }
    }), 200