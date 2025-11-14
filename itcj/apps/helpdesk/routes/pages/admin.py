"""
Rutas de vistas para administradores del helpdesk
"""
from flask import Blueprint, render_template, abort, g, redirect, url_for
from itcj.core.utils.decorators import app_required as web_app_required
from itcj.core.services.authz_service import user_roles_in_app

from . import admin_pages_bp as bp


@bp.route('/home')
@web_app_required('helpdesk', perms=['helpdesk.dashboard.admin'])
def home():
    """
    Dashboard principal de administrador
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'helpdesk/admin/home.html',
        user_roles=user_roles,
        active_page='admin_home'
    )


@bp.route('/assign-tickets')
@web_app_required('helpdesk', perms=['helpdesk.tickets.assign'])
def assign_tickets():
    """
    Vista para asignar y gestionar tickets (antes era secretaría)
    
    Requiere permiso específico: helpdesk.tickets.assign
    - Admins lo tienen por defecto
    - Posición secretary_comp_center lo tiene asignado
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'helpdesk/admin/assign_tickets.html',
        user_roles=user_roles,
        active_page='admin_assign_tickets'
    )


@bp.route('/tickets')
@web_app_required('helpdesk', perms=['helpdesk.tickets.all.read'])
def all_tickets():
    """
    Vista de todos los tickets del sistema (Admin)
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'helpdesk/admin/all_tickets.html',
        user_roles=user_roles,
        active_page='admin_tickets'
    )


@bp.route('/categories')
@web_app_required('helpdesk', perms=['helpdesk.categories.manage'])
def categories():
    """
    Gestión de categorías de tickets
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'helpdesk/admin/categories.html',
        user_roles=user_roles,
        active_page='admin_categories'
    )


@bp.route('/inventory')
@web_app_required('helpdesk', perms=['helpdesk.inventory.view'])
def inventory_list():
    """
    Lista completa de inventario (Admin)
    """
    return redirect(url_for('helpdesk_pages.inventory_pages.items_list'))


@bp.route('/inventory/create')
@web_app_required('helpdesk', perms=['helpdesk.inventory.create'])
def inventory_create():
    """
    Formulario para crear nuevo equipo de inventario
    """
    return redirect(url_for('helpdesk_pages.inventory_pages.item_create'))


@bp.route('/inventory/categories')
@web_app_required('helpdesk', perms=['helpdesk.inventory_categories.manage'])
def inventory_categories():
    """
    Gestión de categorías de inventario
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'helpdesk/admin/inventory_categories.html',
        user_roles=user_roles,
        active_page='admin_inventory_categories'
    )


@bp.route('/inventory/reports')
@web_app_required('helpdesk', perms=['helpdesk.inventory.export'])
def inventory_reports():
    """
    Reportes de inventario
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'helpdesk/admin/inventory_reports.html',
        user_roles=user_roles,
        active_page='admin_inventory_reports'
    )


@bp.route('/stats')
@web_app_required('helpdesk', perms=['helpdesk.stats.view'])
def stats():
    """
    Estadísticas generales del sistema
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'helpdesk/admin/stats.html',
        user_roles=user_roles,
        active_page='admin_stats'
    )