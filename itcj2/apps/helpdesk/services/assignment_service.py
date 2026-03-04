from fastapi import HTTPException
from sqlalchemy import case
from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.apps.helpdesk.models.assignment import Assignment
from itcj2.apps.helpdesk.models.status_log import StatusLog
from itcj2.core.models.user import User
from itcj2.core.services.authz_service import user_roles_in_app
from itcj2.apps.helpdesk.utils.timezone_utils import now_local
import logging

logger = logging.getLogger(__name__)


# ==================== ASIGNAR TICKET ====================
def assign_ticket(
    db: Session,
    ticket_id: int,
    assigned_by_id: int,
    assigned_to_user_id: int = None,
    assigned_to_team: str = None,
    reason: str = None
) -> Assignment:
    """
    Asigna un ticket a un técnico específico o a un equipo.
    """
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    if ticket.status not in ['PENDING', 'ASSIGNED']:
        raise HTTPException(status_code=400, detail='El ticket no puede ser asignado en su estado actual')

    if not assigned_to_user_id and not assigned_to_team:
        raise HTTPException(status_code=400, detail='Debe asignar a un usuario o a un equipo')

    if assigned_to_user_id and assigned_to_team:
        raise HTTPException(status_code=400, detail='No puede asignar a usuario Y equipo simultáneamente')

    assigned_user = None
    if assigned_to_user_id:
        assigned_user = db.get(User, assigned_to_user_id)
        if not assigned_user:
            raise HTTPException(status_code=404, detail='Usuario asignado no encontrado')

        user_roles = user_roles_in_app(db, assigned_to_user_id, 'helpdesk')
        required_role = f'tech_{ticket.area.lower()}'

        if required_role not in user_roles and 'admin' not in user_roles:
            raise HTTPException(
                status_code=400,
                detail=f'El técnico no tiene el rol para atender tickets de {ticket.area}'
            )

    if assigned_to_team:
        valid_teams = ['desarrollo', 'soporte']
        if assigned_to_team not in valid_teams:
            raise HTTPException(status_code=400, detail='Equipo inválido. Debe ser "desarrollo" o "soporte"')

        area_team_map = {
            'DESARROLLO': 'desarrollo',
            'SOPORTE': 'soporte'
        }

        if area_team_map[ticket.area] != assigned_to_team:
            raise HTTPException(
                status_code=400,
                detail=f'El equipo no corresponde al área del ticket ({ticket.area})'
            )

    if ticket.assigned_to_user_id or ticket.assigned_to_team:
        _close_previous_assignment(db, ticket_id)

    assignment = Assignment(
        ticket_id=ticket_id,
        assigned_by_id=assigned_by_id,
        assigned_to_user_id=assigned_to_user_id,
        assigned_to_team=assigned_to_team,
        reason=reason
    )
    db.add(assignment)

    old_status = ticket.status
    ticket.assigned_to_user_id = assigned_to_user_id
    ticket.assigned_to_team = assigned_to_team
    ticket.status = 'ASSIGNED'
    ticket.updated_at = now_local()

    status_log = StatusLog(
        ticket_id=ticket_id,
        from_status=old_status,
        to_status='ASSIGNED',
        changed_by_id=assigned_by_id,
        notes=f'Asignado a {assigned_user.full_name if assigned_to_user_id else assigned_to_team}'
    )
    db.add(status_log)

    try:
        db.commit()

        target = assigned_user.full_name if assigned_to_user_id else f"equipo {assigned_to_team}"
        logger.info(f"Ticket {ticket.ticket_number} asignado a {target}")

        return assignment
    except Exception as e:
        db.rollback()
        logger.error(f"Error al asignar ticket: {e}")
        raise HTTPException(status_code=500, detail='Error al asignar ticket')


# ==================== REASIGNAR TICKET ====================
def reassign_ticket(
    db: Session,
    ticket_id: int,
    reassigned_by_id: int,
    assigned_to_user_id: int = None,
    assigned_to_team: str = None,
    reason: str = None
) -> Assignment:
    """
    Reasigna un ticket que ya estaba asignado.
    """
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    if ticket.status not in ['ASSIGNED', 'IN_PROGRESS']:
        raise HTTPException(status_code=400, detail='Solo se pueden reasignar tickets ya asignados o en progreso')

    if not ticket.assigned_to_user_id and not ticket.assigned_to_team:
        raise HTTPException(status_code=400, detail='El ticket no tiene una asignación previa')

    if not reason:
        reason = 'Ticket reasignado'

    return assign_ticket(
        db=db,
        ticket_id=ticket_id,
        assigned_by_id=reassigned_by_id,
        assigned_to_user_id=assigned_to_user_id,
        assigned_to_team=assigned_to_team,
        reason=reason
    )


# ==================== AUTO-ASIGNARSE ====================
def self_assign_ticket(db: Session, ticket_id: int, technician_id: int) -> Assignment:
    """
    Un técnico se auto-asigna un ticket del equipo.
    """
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    if not ticket.assigned_to_team:
        raise HTTPException(status_code=400, detail='Este ticket no está asignado a un equipo')

    if ticket.assigned_to_user_id:
        raise HTTPException(status_code=400, detail='Este ticket ya está asignado a un técnico específico')

    user_roles = user_roles_in_app(db, technician_id, 'helpdesk')

    required_role = f'tech_{ticket.assigned_to_team}'

    if required_role not in user_roles and 'admin' not in user_roles:
        raise HTTPException(
            status_code=403,
            detail=f'No tienes permiso para tomar tickets del equipo {ticket.assigned_to_team}'
        )

    _close_previous_assignment(db, ticket_id)

    assignment = Assignment(
        ticket_id=ticket_id,
        assigned_by_id=technician_id,
        assigned_to_user_id=technician_id,
        assigned_to_team=None,
        reason='Técnico se auto-asignó el ticket'
    )
    db.add(assignment)

    ticket.assigned_to_user_id = technician_id
    ticket.assigned_to_team = None
    ticket.updated_at = now_local()

    technician = db.get(User, technician_id)
    status_log = StatusLog(
        ticket_id=ticket_id,
        from_status=ticket.status,
        to_status='ASSIGNED',
        changed_by_id=technician_id,
        notes=f'{technician.full_name} se auto-asignó el ticket'
    )
    db.add(status_log)

    try:
        db.commit()
        logger.info(f"Técnico {technician_id} se auto-asignó el ticket {ticket.ticket_number}")
        return assignment
    except Exception as e:
        db.rollback()
        logger.error(f"Error al auto-asignar ticket: {e}")
        raise HTTPException(status_code=500, detail='Error al auto-asignarse el ticket')


# ==================== HISTORIAL DE ASIGNACIONES ====================
def get_assignment_history(db: Session, ticket_id: int) -> list:
    """
    Obtiene el historial completo de asignaciones de un ticket.
    """
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    assignments = (
        db.query(Assignment)
        .filter_by(ticket_id=ticket_id)
        .order_by(Assignment.assigned_at.asc())
        .all()
    )

    return [assignment.to_dict() for assignment in assignments]


# ==================== OBTENER TICKETS DEL EQUIPO ====================
def get_team_tickets(db: Session, team_name: str, technician_id: int = None) -> list:
    """
    Obtiene tickets asignados a un equipo (sin técnico específico).
    """
    if team_name not in ['desarrollo', 'soporte']:
        raise HTTPException(status_code=400, detail='Equipo inválido')

    if technician_id:
        user_roles = user_roles_in_app(db, technician_id, 'helpdesk')
        required_role = f'tech_{team_name}'

        if required_role not in user_roles and 'admin' not in user_roles:
            raise HTTPException(status_code=403, detail=f'No perteneces al equipo {team_name}')

    tickets = (
        db.query(Ticket)
        .filter(
            Ticket.assigned_to_team == team_name,
            Ticket.assigned_to_user_id.is_(None),
            Ticket.status.in_(['ASSIGNED', 'IN_PROGRESS'])
        )
        .order_by(
            case(
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
def _close_previous_assignment(db: Session, ticket_id: int) -> None:
    """
    Cierra la asignación anterior de un ticket (marca unassigned_at).
    """
    last_assignment = (
        db.query(Assignment)
        .filter_by(ticket_id=ticket_id, unassigned_at=None)
        .order_by(Assignment.assigned_at.desc())
        .first()
    )

    if last_assignment:
        last_assignment.unassigned_at = now_local()
        logger.debug(f"Cerrada asignación previa del ticket {ticket_id}")


def can_user_assign_tickets(db: Session, user_id: int) -> bool:
    """
    Verifica si un usuario puede asignar tickets.
    """
    user_roles = user_roles_in_app(db, user_id, 'helpdesk')
    return 'admin' in user_roles or 'secretary' in user_roles


def get_technicians_by_area(db: Session, area: str) -> list:
    """
    Obtiene la lista de técnicos disponibles para un área.
    """
    from itcj2.core.models.user_app_role import UserAppRole
    from itcj2.core.models.role import Role
    from itcj2.core.models.app import App

    app = db.query(App).filter_by(key='helpdesk').first()
    if not app:
        return []

    role_name = f'tech_{area.lower()}'

    technicians = (
        db.query(User)
        .join(UserAppRole, UserAppRole.user_id == User.id)
        .join(Role, Role.id == UserAppRole.role_id)
        .filter(
            UserAppRole.app_id == app.id,
            Role.name == role_name
        )
        .all()
    )

    return technicians
