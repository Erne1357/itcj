from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.apps.helpdesk.models.collaborator import TicketCollaborator
from itcj2.core.models.user import User
from itcj2.models.base import paginate
import logging

logger = logging.getLogger(__name__)


# ==================== AGREGAR COLABORADOR ====================
def add_collaborator(
    db: Session,
    ticket_id: int,
    user_id: int,
    collaboration_role: str = None,
    time_invested_minutes: int = None,
    notes: str = None,
    added_by_id: int = None
) -> TicketCollaborator:
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail='Usuario no encontrado')

    if not collaboration_role:
        collaboration_role = suggest_collaboration_role(db, user_id, ticket_id)

    try:
        TicketCollaborator.validate_role(collaboration_role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    existing = db.query(TicketCollaborator).filter_by(
        ticket_id=ticket_id,
        user_id=user_id
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail='Este colaborador ya está agregado al ticket')

    if time_invested_minutes is not None and time_invested_minutes < 0:
        raise HTTPException(status_code=400, detail='El tiempo invertido no puede ser negativo')

    if ticket.assigned_to_user_id == user_id and collaboration_role != 'LEAD':
        logger.warning(f'Usuario {user_id} es el asignado del ticket {ticket_id}, forzando rol LEAD')
        collaboration_role = 'LEAD'

    collaborator = TicketCollaborator(
        ticket_id=ticket_id,
        user_id=user_id,
        collaboration_role=collaboration_role,
        time_invested_minutes=time_invested_minutes,
        notes=notes,
        added_by_id=added_by_id
    )

    db.add(collaborator)

    try:
        db.commit()
        logger.info(f'Colaborador {user_id} agregado al ticket {ticket_id} como {collaboration_role}')
        return collaborator
    except Exception as e:
        db.rollback()
        logger.error(f'Error al agregar colaborador: {e}')
        raise HTTPException(status_code=500, detail='Error al agregar colaborador')


# ==================== AGREGAR MÚLTIPLES COLABORADORES ====================
def add_multiple_collaborators(
    db: Session,
    ticket_id: int,
    collaborators_data: list,
    added_by_id: int = None
) -> list:
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    if not collaborators_data or not isinstance(collaborators_data, list):
        raise HTTPException(status_code=400, detail='Se requiere una lista de colaboradores')

    created_collaborators = []

    try:
        for data in collaborators_data:
            if 'user_id' not in data:
                raise ValueError('Cada colaborador debe tener user_id')

            existing = db.query(TicketCollaborator).filter_by(
                ticket_id=ticket_id,
                user_id=data['user_id']
            ).first()

            if existing:
                logger.warning(f'Colaborador {data["user_id"]} ya existe en ticket {ticket_id}, saltando...')
                continue

            user = db.get(User, data['user_id'])
            if not user:
                raise ValueError(f'Usuario {data["user_id"]} no encontrado')

            role = data.get('collaboration_role')
            if not role:
                role = suggest_collaboration_role(db, data['user_id'], ticket_id)

            if ticket.assigned_to_user_id == data['user_id']:
                role = 'LEAD'

            TicketCollaborator.validate_role(role)

            collaborator = TicketCollaborator(
                ticket_id=ticket_id,
                user_id=data['user_id'],
                collaboration_role=role,
                time_invested_minutes=data.get('time_invested_minutes'),
                notes=data.get('notes'),
                added_by_id=added_by_id
            )

            db.add(collaborator)
            created_collaborators.append(collaborator)

        db.commit()
        logger.info(f'{len(created_collaborators)} colaboradores agregados al ticket {ticket_id}')
        return created_collaborators

    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error(f'Error al agregar colaboradores: {e}')
        raise HTTPException(status_code=500, detail='Error al agregar colaboradores')


# ==================== REMOVER COLABORADOR ====================
def remove_collaborator(db: Session, ticket_id: int, user_id: int) -> None:
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    collaborator = db.query(TicketCollaborator).filter_by(
        ticket_id=ticket_id,
        user_id=user_id
    ).first()

    if not collaborator:
        raise HTTPException(status_code=404, detail='Colaborador no encontrado en este ticket')

    if ticket.assigned_to_user_id == user_id:
        raise HTTPException(status_code=400, detail='No se puede remover al técnico asignado principal')

    try:
        db.delete(collaborator)
        db.commit()
        logger.info(f'Colaborador {user_id} removido del ticket {ticket_id}')
    except Exception as e:
        db.rollback()
        logger.error(f'Error al remover colaborador: {e}')
        raise HTTPException(status_code=500, detail='Error al remover colaborador')


# ==================== ACTUALIZAR COLABORADOR ====================
def update_collaborator(
    db: Session,
    ticket_id: int,
    user_id: int,
    time_invested_minutes: int = None,
    notes: str = None
) -> TicketCollaborator:
    collaborator = db.query(TicketCollaborator).filter_by(
        ticket_id=ticket_id,
        user_id=user_id
    ).first()

    if not collaborator:
        raise HTTPException(status_code=404, detail='Colaborador no encontrado en este ticket')

    if time_invested_minutes is not None:
        if time_invested_minutes < 0:
            raise HTTPException(status_code=400, detail='El tiempo invertido no puede ser negativo')
        collaborator.time_invested_minutes = time_invested_minutes

    if notes is not None:
        collaborator.notes = notes

    try:
        db.commit()
        logger.info(f'Colaborador {user_id} actualizado en ticket {ticket_id}')
        return collaborator
    except Exception as e:
        db.rollback()
        logger.error(f'Error al actualizar colaborador: {e}')
        raise HTTPException(status_code=500, detail='Error al actualizar colaborador')


# ==================== OBTENER COLABORADORES ====================
def get_ticket_collaborators(db: Session, ticket_id: int) -> list:
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    collaborators = (
        db.query(TicketCollaborator)
        .filter_by(ticket_id=ticket_id)
        .order_by(TicketCollaborator.added_at.asc())
        .all()
    )

    return collaborators


# ==================== SUGERIR ROL ====================
def suggest_collaboration_role(db: Session, user_id: int, ticket_id: int) -> str:
    from itcj2.core.services.authz_service import user_roles_in_app

    user = db.get(User, user_id)
    if not user:
        return 'COLLABORATOR'

    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        return 'COLLABORATOR'

    if ticket.assigned_to_user_id == user_id:
        return 'LEAD'

    user_roles = user_roles_in_app(db, user_id, 'helpdesk')

    if 'department_head' in user_roles or 'admin' in user_roles:
        return 'SUPERVISOR'

    if 'resident' in user_roles or 'social_service' in user_roles:
        return 'TRAINEE'

    if 'tech_desarrollo' in user_roles or 'tech_soporte' in user_roles:
        return 'COLLABORATOR'

    return 'CONSULTANT'


# ==================== TICKETS DONDE COLABORÉ ====================
def get_tickets_where_user_collaborated(
    db: Session,
    user_id: int,
    page: int = 1,
    per_page: int = 20
) -> dict:
    collab_ticket_ids = (
        db.query(TicketCollaborator.ticket_id)
        .filter(TicketCollaborator.user_id == user_id)
        .subquery()
    )

    query = db.query(Ticket).filter(Ticket.id.in_(collab_ticket_ids))
    query = query.order_by(Ticket.created_at.desc())

    pagination = paginate(query, page=page, per_page=per_page)

    return {
        'tickets': [t.to_dict(include_relations=True) for t in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page,
        'per_page': per_page,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev
    }


# ==================== VALIDACIONES ====================
def can_user_manage_collaborators(db: Session, user_id: int, ticket_id: int) -> bool:
    from itcj2.core.services.authz_service import user_roles_in_app

    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        return False

    user_roles = user_roles_in_app(db, user_id, 'helpdesk')

    if 'admin' in user_roles or 'secretary' in user_roles:
        return True

    if ticket.assigned_to_user_id == user_id:
        return True

    return False


# ==================== ESTADÍSTICAS ====================
def get_user_collaboration_stats(db: Session, user_id: int, days: int = 30) -> dict:
    start_date = datetime.now() - timedelta(days=days)

    total_collaborations = (
        db.query(TicketCollaborator)
        .filter(TicketCollaborator.user_id == user_id)
        .join(Ticket)
        .filter(Ticket.created_at >= start_date)
        .count()
    )

    role_counts = {}
    for role in TicketCollaborator.VALID_ROLES:
        count = (
            db.query(TicketCollaborator)
            .filter(
                TicketCollaborator.user_id == user_id,
                TicketCollaborator.collaboration_role == role
            )
            .join(Ticket)
            .filter(Ticket.created_at >= start_date)
            .count()
        )
        role_counts[role.lower()] = count

    total_time = (
        db.query(func.sum(TicketCollaborator.time_invested_minutes))
        .filter(TicketCollaborator.user_id == user_id)
        .join(Ticket)
        .filter(Ticket.created_at >= start_date)
        .scalar()
    ) or 0

    return {
        'user_id': user_id,
        'period_days': days,
        'total_collaborations': total_collaborations,
        'by_role': role_counts,
        'total_minutes': total_time,
        'total_hours': round(total_time / 60, 2)
    }
