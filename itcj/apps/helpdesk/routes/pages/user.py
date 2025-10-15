# itcj/apps/helpdesk/routes/pages/user.py
from flask import render_template, g, request, abort
from itcj.core.utils.decorators import app_required
from . import user_pages_bp
import logging

logger = logging.getLogger(__name__)


@user_pages_bp.get('/create')
@app_required('helpdesk', perms=['helpdesk.create'])
def create_ticket():
    """Página para crear un nuevo ticket"""
    return render_template('user/create_ticket.html', title="Crear Ticket")


@user_pages_bp.get('/my-tickets')
@app_required('helpdesk', perms=['helpdesk.own.read'])
def my_tickets():
    """Lista de tickets del usuario"""
    return render_template('user/my_tickets.html', title="Mis Tickets")


@user_pages_bp.get('/tickets/<int:ticket_id>')
@app_required('helpdesk', perms=['helpdesk.own.read'])
def ticket_detail(ticket_id):
    """Vista de detalle de un ticket específico"""
    return render_template('user/ticket_detail.html', 
                         title=f"Ticket #{ticket_id}", 
                         ticket_id=ticket_id)