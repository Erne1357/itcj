# itcj/apps/helpdesk/routes/pages/user.py
from flask import render_template, g, request, abort
from itcj.core.utils.decorators import app_required as web_app_required
from itcj.core.services.authz_service import user_roles_in_app
from itcj.core.models.position import UserPosition
from itcj.core.models.department import Department
from itcj.apps.helpdesk.models.ticket import Ticket
from . import user_pages_bp
import logging

logger = logging.getLogger(__name__)

MAX_UNRATED_TICKETS = 3


@user_pages_bp.get('/create')
@web_app_required('helpdesk', perms=['helpdesk.tickets.page.create'])
def create_ticket():
    """Página para crear un nuevo ticket"""
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')

    # Verificar si tiene tickets sin evaluar
    unrated_count = Ticket.query.filter(
        Ticket.requester_id == user_id,
        Ticket.status.in_(['RESOLVED_SUCCESS', 'RESOLVED_FAILED']),
        Ticket.rating_attention.is_(None)
    ).count()

    # Determinar si el usuario puede crear tickets para otros
    can_create_for_other = False

    # Verificar si es admin
    if 'admin' in user_roles:
        can_create_for_other = True
    else:
        # Verificar si pertenece al Centro de Cómputo en alguno de sus puestos activos
        user_positions = UserPosition.query.filter_by(
            user_id=user_id,
            is_active=True
        ).all()

        for user_position in user_positions:
            if user_position.position and user_position.position.department:
                # Verificar si el departamento es comp_center
                if user_position.position.department.code == 'comp_center':
                    can_create_for_other = True
                    break

    return render_template(
        'helpdesk/user/create_ticket.html',
        title="Crear Ticket",
        user_roles=user_roles,
        can_create_for_other=can_create_for_other,
        unrated_count=unrated_count,
        max_unrated=MAX_UNRATED_TICKETS,
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
        user_id=user_id,  # Pasar el ID del usuario actual
        user_roles=user_roles,
        active_page='my_tickets'
    )