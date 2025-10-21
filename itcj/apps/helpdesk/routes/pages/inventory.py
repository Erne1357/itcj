"""
Rutas de vistas para el módulo de inventario
"""
from flask import Blueprint, render_template, abort, g
from itcj.core.utils.decorators import app_required as web_app_required
from itcj.core.services.authz_service import user_roles_in_app

from . import inventory_pages_bp as bp


@bp.route('/dashboard')
@web_app_required('helpdesk', perms=['helpdesk.inventory.view'])
def dashboard():
    """
    Dashboard principal de inventario (Admin/Secretaría)
    Muestra estadísticas, alertas y actividad reciente
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'inventory/dashboard.html',
        user_roles=user_roles,
        active_page='inventory_dashboard'
    )


@bp.route('/items')
@web_app_required('helpdesk')
def items_list():
    """
    Lista de equipos del inventario
    - Admin/Secretaría: Todos los equipos
    - Jefe Depto: Solo su departamento
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    # Determinar si puede ver todos o solo su departamento
    can_view_all = 'admin' in user_roles or 'secretary' in user_roles
    
    return render_template(
        'inventory/items_list.html',
        user_roles=user_roles,
        can_view_all=can_view_all,
        active_page='inventory_items'
    )


@bp.route('/items/create')
@web_app_required('helpdesk', perms=['helpdesk.inventory.create'])
def item_create():
    """
    Formulario para registrar nuevo equipo (Admin/Secretaría)
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'inventory/item_create.html',
        user_roles=user_roles,
        active_page='inventory_items'
    )


@bp.route('/items/<int:item_id>')
@web_app_required('helpdesk')
def item_detail(item_id):
    """
    Ver detalle completo de un equipo + historial
    Valida permisos según rol
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'inventory/item_detail.html',
        item_id=item_id,
        user_roles=user_roles,
        active_page='inventory_items'
    )


@bp.route('/my-equipment')
@web_app_required('helpdesk')
def my_equipment():
    """
    Equipos asignados al usuario actual (Solo lectura)
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'inventory/my_equipment.html',
        user_roles=user_roles,
        active_page='inventory_my_equipment'
    )


@bp.route('/assign')
@web_app_required('helpdesk', perms=['helpdesk.inventory.assign'])
def assign_equipment():
    """
    Interfaz para asignar equipos a usuarios (Jefe Depto/Admin)
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'inventory/assign_equipment.html',
        user_roles=user_roles,
        active_page='inventory_assign'
    )


@bp.route('/reports/warranty')
@web_app_required('helpdesk', perms=['helpdesk.inventory.stats'])
def warranty_report():
    """
    Reporte de garantías
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'inventory/reports/warranty.html',
        user_roles=user_roles,
        active_page='inventory_reports'
    )


@bp.route('/reports/maintenance')
@web_app_required('helpdesk', perms=['helpdesk.inventory.stats'])
def maintenance_report():
    """
    Reporte de mantenimientos
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'inventory/reports/maintenance.html',
        user_roles=user_roles,
        active_page='inventory_reports'
    )


@bp.route('/reports/lifecycle')
@web_app_required('helpdesk', perms=['helpdesk.inventory.stats'])
def lifecycle_report():
    """
    Reporte de ciclo de vida (antigüedad)
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'inventory/reports/lifecycle.html',
        user_roles=user_roles,
        active_page='inventory_reports'
    )