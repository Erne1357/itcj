from datetime import datetime
from flask import abort
from itcj.core.extensions import db
from itcj.apps.helpdesk.models import Ticket, Assignment, StatusLog
from itcj.core.models.user import User
from itcj.core.services.authz_service import user_roles_in_app
import logging

logger = logging.getLogger(__name__)


# ==================== ASIGNAR TICKET ====================
def assign_ticket(
    ticket_id: int,
    assigned_by_id: int,
    assigned_to_user_id: int = None,
    assigned_to_team: str = None,
    reason: str = None
) -> Assignment:
    """
    Asigna un ticket a un técnico específico o a un equipo.
    
    Args:
        ticket_id: ID del ticket a asignar
        assigned_by_id: ID del usuario que asigna (secretaría/admin)
        assigned_to_user_id: ID del técnico asignado (opcional)
        assigned_to_team: Equipo asignado: 'desarrollo' o 'soporte' (opcional)
        reason: Razón de la asignación (opcional)
    
    Returns:
        Assignment creado
    
    Raises:
        404: Si el ticket o usuario no existen
        400: Si los parámetros son inválidos
        403: Si el usuario no tiene permiso para asignar
    """
    # Validar ticket
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        abort(404, description='Ticket no encontrado')
    
    # Validar que el ticket esté en un estado asignable
    if ticket.status not in ['PENDING', 'ASSIGNED']:
        abort(400, description='El ticket no puede ser asignado en su estado actual')
    
    # Validar parámetros: debe ser usuario O equipo, no ambos ni ninguno
    if not assigned_to_user_id and not assigned_to_team:
        abort(400, description='Debe asignar a un usuario o a un equipo')
    
    if assigned_to_user_id and assigned_to_team:
        abort(400, description='No puede asignar a usuario Y equipo simultáneamente')
    
    # Validar usuario asignado
    if assigned_to_user_id:
        assigned_user = User.query.get(assigned_to_user_id)
        if not assigned_user:
            abort(404, description='Usuario asignado no encontrado')
        
        # Validar que el técnico tenga el rol correcto para el área
        user_roles = user_roles_in_app(assigned_to_user_id, 'helpdesk')
        required_role = f'tech_{ticket.area.lower()}'
        
        if required_role not in user_roles and 'admin' not in user_roles:
            abort(400, description=f'El técnico no tiene el rol para atender tickets de {ticket.area}')
    
    # Validar equipo
    if assigned_to_team:
        valid_teams = ['desarrollo', 'soporte']
        if assigned_to_team not in valid_teams:
            abort(400, description='Equipo inválido. Debe ser "desarrollo" o "soporte"')
        
        # Verificar que el equipo corresponda al área del ticket
        area_team_map = {
            'DESARROLLO': 'desarrollo',
            'SOPORTE': 'soporte'
        }
        
        if area_team_map[ticket.area] != assigned_to_team:
            abort(400, description=f'El equipo no corresponde al área del ticket ({ticket.area})')
    
    # Si ya estaba asignado, marcar la asignación anterior como finalizada
    if ticket.assigned_to_user_id or ticket.assigned_to_team:
        _close_previous_assignment(ticket_id)
    
    # Crear nueva asignación
    assignment = Assignment(
        ticket_id=ticket_id,
        assigned_by_id=assigned_by_id,
        assigned_to_user_id=assigned_to_user_id,
        assigned_to_team=assigned_to_team,
        reason=reason
    )
    db.session.add(assignment)
    
    # Actualizar ticket
    old_status = ticket.status
    ticket.assigned_to_user_id = assigned_to_user_id
    ticket.assigned_to_team = assigned_to_team
    ticket.status = 'ASSIGNED'
    ticket.updated_at = datetime.utcnow()
    
    # Registrar cambio de estado
    status_log = StatusLog(
        ticket_id=ticket_id,
        from_status=old_status,
        to_status='ASSIGNED',
        changed_by_id=assigned_by_id,
        notes=f'Asignado a {assigned_user.name if assigned_to_user_id else assigned_to_team}'
    )
    db.session.add(status_log)
    
    try:
        db.session.commit()
        
        target = assigned_user.name if assigned_to_user_id else f"equipo {assigned_to_team}"
        logger.info(f"Ticket {ticket.ticket_number} asignado a {target}")
        
        return assignment
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al asignar ticket: {e}")
        abort(500, description='Error al asignar ticket')


# ==================== REASIGNAR TICKET ====================
def reassign_ticket(
    ticket_id: int,
    reassigned_by_id: int,
    assigned_to_user_id: int = None,
    assigned_to_team: str = None,
    reason: str = None
) -> Assignment:
    """
    Reasigna un ticket que ya estaba asignado.
    
    Args:
        ticket_id: ID del ticket
        reassigned_by_id: ID del usuario que reasigna
        assigned_to_user_id: Nuevo técnico asignado (opcional)
        assigned_to_team: Nuevo equipo asignado (opcional)
        reason: Razón de la reasignación (recomendado)
    
    Returns:
        Nueva asignación creada
    
    Raises:
        404: Si el ticket no existe
        400: Si el ticket no estaba asignado o parámetros inválidos
    """
    # Validar ticket
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        abort(404, description='Ticket no encontrado')
    
    # Validar que esté asignado
    if ticket.status not in ['ASSIGNED', 'IN_PROGRESS']:
        abort(400, description='Solo se pueden reasignar tickets ya asignados o en progreso')
    
    if not ticket.assigned_to_user_id and not ticket.assigned_to_team:
        abort(400, description='El ticket no tiene una asignación previa')
    
    # Usar la función assign_ticket (que ya valida todo)
    # Primero guardamos la razón de reasignación
    if not reason:
        reason = 'Ticket reasignado'
    
    return assign_ticket(
        ticket_id=ticket_id,
        assigned_by_id=reassigned_by_id,
        assigned_to_user_id=assigned_to_user_id,
        assigned_to_team=assigned_to_team,
        reason=reason
    )


# ==================== AUTO-ASIGNARSE ====================
def self_assign_ticket(ticket_id: int, technician_id: int) -> Assignment:
    """
    Un técnico se auto-asigna un ticket del equipo.
    
    Args:
        ticket_id: ID del ticket
        technician_id: ID del técnico que se auto-asigna
    
    Returns:
        Asignación creada
    
    Raises:
        404: Si el ticket no existe
        400: Si el ticket no está disponible para auto-asignación
        403: Si el técnico no tiene permiso
    """
    # Validar ticket
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        abort(404, description='Ticket no encontrado')
    
    # Validar que esté asignado a un equipo (no a persona específica)
    if not ticket.assigned_to_team:
        abort(400, description='Este ticket no está asignado a un equipo')
    
    if ticket.assigned_to_user_id:
        abort(400, description='Este ticket ya está asignado a un técnico específico')
    
    # Validar que el técnico tenga el rol correcto
    user_roles = user_roles_in_app(technician_id, 'helpdesk')
    
    # Determinar el rol requerido según el equipo asignado
    required_role = f'tech_{ticket.assigned_to_team}'  # tech_desarrollo o tech_soporte
    
    if required_role not in user_roles and 'admin' not in user_roles:
        abort(403, description=f'No tienes permiso para tomar tickets del equipo {ticket.assigned_to_team}')
    
    # Cerrar asignación anterior (grupal)
    _close_previous_assignment(ticket_id)
    
    # Crear nueva asignación individual
    assignment = Assignment(
        ticket_id=ticket_id,
        assigned_by_id=technician_id,  # Se asignó a sí mismo
        assigned_to_user_id=technician_id,
        assigned_to_team=None,  # Ya no es del equipo, es personal
        reason='Técnico se auto-asignó el ticket'
    )
    db.session.add(assignment)
    
    # Actualizar ticket
    ticket.assigned_to_user_id = technician_id
    ticket.assigned_to_team = None
    ticket.updated_at = datetime.utcnow()
    
    # Registrar en log
    technician = User.query.get(technician_id)
    status_log = StatusLog(
        ticket_id=ticket_id,
        from_status=ticket.status,
        to_status='ASSIGNED',
        changed_by_id=technician_id,
        notes=f'{technician.name} se auto-asignó el ticket'
    )
    db.session.add(status_log)
    
    try:
        db.session.commit()
        logger.info(f"Técnico {technician_id} se auto-asignó el ticket {ticket.ticket_number}")
        return assignment
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al auto-asignar ticket: {e}")
        abort(500, description='Error al auto-asignarse el ticket')


# ==================== HISTORIAL DE ASIGNACIONES ====================
def get_assignment_history(ticket_id: int) -> list[dict]:
    """
    Obtiene el historial completo de asignaciones de un ticket.
    
    Args:
        ticket_id: ID del ticket
    
    Returns:
        Lista de asignaciones en orden cronológico
    
    Raises:
        404: Si el ticket no existe
    """
    # Validar ticket
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        abort(404, description='Ticket no encontrado')
    
    # Obtener todas las asignaciones
    assignments = (
        Assignment.query
        .filter_by(ticket_id=ticket_id)
        .order_by(Assignment.assigned_at.asc())
        .all()
    )
    
    return [assignment.to_dict() for assignment in assignments]


# ==================== OBTENER TICKETS DEL EQUIPO ====================
def get_team_tickets(team_name: str, technician_id: int = None) -> list[Ticket]:
    """
    Obtiene tickets asignados a un equipo (sin técnico específico).
    
    Args:
        team_name: 'desarrollo' o 'soporte'
        technician_id: ID del técnico (para validar que pertenezca al equipo)
    
    Returns:
        Lista de tickets disponibles para auto-asignación
    
    Raises:
        400: Si el equipo es inválido
        403: Si el técnico no pertenece al equipo
    """
    # Validar equipo
    if team_name not in ['desarrollo', 'soporte']:
        abort(400, description='Equipo inválido')
    
    # Si se proporciona técnico, validar que pertenezca al equipo
    if technician_id:
        user_roles = user_roles_in_app(technician_id, 'helpdesk')
        required_role = f'tech_{team_name}'
        
        if required_role not in user_roles and 'admin' not in user_roles:
            abort(403, description=f'No perteneces al equipo {team_name}')
    
    # Obtener tickets del equipo (sin técnico específico asignado)
    tickets = (
        Ticket.query
        .filter(
            Ticket.assigned_to_team == team_name,
            Ticket.assigned_to_user_id.is_(None),
            Ticket.status.in_(['ASSIGNED', 'IN_PROGRESS'])
        )
        .order_by(
            db.case(
                (Ticket.priority == 'URGENTE', 1),
                (Ticket.priority == 'ALTA', 2),
                (Ticket.priority == 'MEDIA', 3),
                (Ticket.priority == 'BAJA', 4),
                else_=5
            ),
            Ticket.created_at.asc()
        )
        .all()
    )
    
    return tickets


# ==================== FUNCIONES AUXILIARES ====================
def _close_previous_assignment(ticket_id: int) -> None:
    """
    Cierra la asignación anterior de un ticket (marca unassigned_at).
    
    Args:
        ticket_id: ID del ticket
    """
    # Obtener la última asignación activa
    last_assignment = (
        Assignment.query
        .filter_by(ticket_id=ticket_id, unassigned_at=None)
        .order_by(Assignment.assigned_at.desc())
        .first()
    )
    
    if last_assignment:
        last_assignment.unassigned_at = datetime.utcnow()
        logger.debug(f"Cerrada asignación previa del ticket {ticket_id}")


def can_user_assign_tickets(user_id: int) -> bool:
    """
    Verifica si un usuario puede asignar tickets.
    
    Args:
        user_id: ID del usuario
    
    Returns:
        True si puede asignar, False si no
    """
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    return 'admin' in user_roles or 'secretary' in user_roles


def get_technicians_by_area(area: str) -> list[User]:
    """
    Obtiene la lista de técnicos disponibles para un área.
    
    Args:
        area: 'DESARROLLO' o 'SOPORTE'
    
    Returns:
        Lista de usuarios técnicos
    """
    from itcj.core.models.user_app_role import UserAppRole
    from itcj.core.models.role import Role
    from itcj.core.models.app import App
    
    # Obtener la app helpdesk
    app = App.query.filter_by(key='helpdesk').first()
    if not app:
        return []
    
    # Determinar el rol según el área
    role_name = f'tech_{area.lower()}'
    
    # Obtener técnicos con ese rol
    technicians = (
        db.session.query(User)
        .join(UserAppRole, UserAppRole.user_id == User.id)
        .join(Role, Role.id == UserAppRole.role_id)
        .filter(
            UserAppRole.app_id == app.id,
            Role.name == role_name
        )
        .all()
    )
    
    return technicians