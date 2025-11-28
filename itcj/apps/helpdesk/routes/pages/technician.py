# itcj/apps/helpdesk/routes/pages/technician.py
"""
Rutas de vistas para técnicos del helpdesk
"""
from flask import render_template, g
from itcj.core.utils.decorators import app_required as web_app_required
from itcj.core.services.authz_service import user_roles_in_app

from . import technician_pages_bp as bp


@bp.route('/dashboard')
@web_app_required('helpdesk', perms=['helpdesk.dashboard.technician'])
def dashboard():
    """
    Dashboard personal del técnico
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'helpdesk/technician/dashboard.html',
        user_roles=user_roles,
        active_page='tech_dashboard'
    )


@bp.route('/my-assignments')
@web_app_required('helpdesk', perms=['helpdesk.tickets.page.my_tickets'])
def my_assignments():
    """
    Tickets asignados al técnico actual
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'helpdesk/technician/my_assignments.html',
        user_roles=user_roles,
        active_page='tech_assignments'
    )


@bp.route('/team')
@web_app_required('helpdesk', perms=['helpdesk.tickets.page.team'])
def team():
    """
    Vista de tickets del equipo técnico
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'helpdesk/technician/team.html',
        user_roles=user_roles,
        active_page='tech_team'
    )


@bp.route('/tickets/<int:ticket_id>')
@web_app_required('helpdesk', perms=['helpdesk.tickets.page.my_tickets'])
def ticket_detail(ticket_id):
    """
    Vista detallada de un ticket para técnico
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'helpdesk/technician/ticket_detail.html',
        ticket_id=ticket_id,
        user_roles=user_roles,
        active_page='tech_assignments'
    )