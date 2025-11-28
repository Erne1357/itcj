# itcj/apps/helpdesk/routes/pages/user.py
from flask import render_template, g, request, abort
from itcj.core.utils.decorators import app_required as web_app_required
from itcj.core.services.authz_service import user_roles_in_app
from . import user_pages_bp
import logging

logger = logging.getLogger(__name__)


@user_pages_bp.get('/create')
@web_app_required('helpdesk', perms=['helpdesk.tickets.page.create'])
def create_ticket():
    """Página para crear un nuevo ticket"""
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'helpdesk/user/create_ticket.html', 
        title="Crear Ticket",
        user_roles=user_roles,
        active_page='create_ticket'
    )


@user_pages_bp.get('/my-tickets')
@web_app_required('helpdesk', perms=['helpdesk.tickets.page.my_tickets'])
def my_tickets():
    """Lista de tickets del usuario"""
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'helpdesk/user/my_tickets.html', 
        title="Mis Tickets",
        user_roles=user_roles,
        active_page='my_tickets'
    )


@user_pages_bp.get('/tickets/<int:ticket_id>')
@web_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own','helpdesk.tickets.api.read.all'])
def ticket_detail(ticket_id):
    """Vista de detalle de un ticket específico"""
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    return render_template(
        'helpdesk/user/ticket_detail.html', 
        title=f"Ticket #{ticket_id}", 
        ticket_id=ticket_id,
        user_roles=user_roles,
        active_page='my_tickets'
    )