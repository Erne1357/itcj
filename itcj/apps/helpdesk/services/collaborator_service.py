from flask import abort
from itcj.core.extensions import db
from itcj.apps.helpdesk.models import Ticket, TicketCollaborator
from itcj.core.models.user import User
from itcj.core.services.authz_service import user_roles_in_app
import logging

logger = logging.getLogger(__name__)


# ==================== AGREGAR COLABORADOR ====================
def add_collaborator(
    ticket_id: int,
    user_id: int,
    collaboration_role: str = None,
    time_invested_minutes: int = None,
    notes: str = None,
    added_by_id: int = None
) -> TicketCollaborator:
    """
    Agrega un colaborador a un ticket.
    
    Args:
        ticket_id: ID del ticket
        user_id: ID del usuario colaborador
        collaboration_role: Rol en la colaboración (si no se provee, se auto-sugiere)
        time_invested_minutes: Tiempo invertido (opcional)
        notes: Notas del colaborador (opcional)
        added_by_id: ID de quien agregó (opcional)
    
    Returns:
        TicketCollaborator creado
    
    Raises:
        404: Si el ticket o usuario no existen
        400: Si el rol es inválido o el colaborador ya existe
    """
    # Validar ticket
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        abort(404, description='Ticket no encontrado')
    
    # Validar usuario
    user = User.query.get(user_id)
    if not user:
        abort(404, description='Usuario no encontrado')
    
    # Auto-sugerir rol si no se proporciona
    if not collaboration_role:
        collaboration_role = suggest_collaboration_role(user_id, ticket_id)
    
    # Validar rol
    try:
        TicketCollaborator.validate_role(collaboration_role)
    except ValueError as e:
        abort(400, description=str(e))
    
    # Validar que no exista ya
    existing = TicketCollaborator.query.filter_by(
        ticket_id=ticket_id,
        user_id=user_id
    ).first()
    
    if existing:
        abort(400, description='Este colaborador ya está agregado al ticket')
    
    # Validar tiempo si se proporciona
    if time_invested_minutes is not None and time_invested_minutes < 0:
        abort(400, description='El tiempo invertido no puede ser negativo')
    
    # Si el usuario es el asignado principal, el rol DEBE ser LEAD
    if ticket.assigned_to_user_id == user_id and collaboration_role != 'LEAD':
        logger.warning(f'Usuario {user_id} es el asignado del ticket {ticket_id}, forzando rol LEAD')
        collaboration_role = 'LEAD'
    
    # Crear colaborador
    collaborator = TicketCollaborator(
        ticket_id=ticket_id,
        user_id=user_id,
        collaboration_role=collaboration_role,
        time_invested_minutes=time_invested_minutes,
        notes=notes,
        added_by_id=added_by_id
    )
    
    db.session.add(collaborator)
    
    try:
        db.session.commit()
        logger.info(f'Colaborador {user_id} agregado al ticket {ticket_id} como {collaboration_role}')
        return collaborator
    except Exception as e:
        db.session.rollback()
        logger.error(f'Error al agregar colaborador: {e}')
        abort(500, description='Error al agregar colaborador')


# ==================== AGREGAR MÚLTIPLES COLABORADORES ====================
def add_multiple_collaborators(
    ticket_id: int,
    collaborators_data: list[dict],
    added_by_id: int = None
) -> list[TicketCollaborator]:
    """
    Agrega múltiples colaboradores en una sola transacción.
    
    Args:
        ticket_id: ID del ticket
        collaborators_data: Lista de dicts con {user_id, collaboration_role, time_invested_minutes, notes}
        added_by_id: ID de quien agregó
    
    Returns:
        Lista de TicketCollaborator creados
    
    Raises:
        404: Si el ticket no existe
        400: Si algún dato es inválido
    """
    # Validar ticket
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        abort(404, description='Ticket no encontrado')
    
    if not collaborators_data or not isinstance(collaborators_data, list):
        abort(400, description='Se requiere una lista de colaboradores')
    
    created_collaborators = []
    
    try:
        for data in collaborators_data:
            if 'user_id' not in data:
                raise ValueError('Cada colaborador debe tener user_id')
            
            # Verificar que no exista ya
            existing = TicketCollaborator.query.filter_by(
                ticket_id=ticket_id,
                user_id=data['user_id']
            ).first()
            
            if existing:
                logger.warning(f'Colaborador {data["user_id"]} ya existe en ticket {ticket_id}, saltando...')
                continue
            
            # Validar usuario
            user = User.query.get(data['user_id'])
            if not user:
                raise ValueError(f'Usuario {data["user_id"]} no encontrado')
            
            # Auto-sugerir rol si no se provee
            role = data.get('collaboration_role')
            if not role:
                role = suggest_collaboration_role(data['user_id'], ticket_id)
            
            # Si es el asignado, forzar LEAD
            if ticket.assigned_to_user_id == data['user_id']:
                role = 'LEAD'
            
            # Validar rol
            TicketCollaborator.validate_role(role)
            
            # Crear colaborador
            collaborator = TicketCollaborator(
                ticket_id=ticket_id,
                user_id=data['user_id'],
                collaboration_role=role,
                time_invested_minutes=data.get('time_invested_minutes'),
                notes=data.get('notes'),
                added_by_id=added_by_id
            )
            
            db.session.add(collaborator)
            created_collaborators.append(collaborator)
        
        db.session.commit()
        logger.info(f'{len(created_collaborators)} colaboradores agregados al ticket {ticket_id}')
        return created_collaborators
        
    except ValueError as e:
        db.session.rollback()
        abort(400, description=str(e))
    except Exception as e:
        db.session.rollback()
        logger.error(f'Error al agregar colaboradores: {e}')
        abort(500, description='Error al agregar colaboradores')


# ==================== REMOVER COLABORADOR ====================
def remove_collaborator(ticket_id: int, user_id: int) -> None:
    """
    Remueve un colaborador de un ticket.
    
    Args:
        ticket_id: ID del ticket
        user_id: ID del usuario a remover
    
    Raises:
        404: Si el ticket o colaborador no existen
        400: Si se intenta remover al asignado principal
    """
    # Validar ticket
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        abort(404, description='Ticket no encontrado')
    
    # Buscar colaborador
    collaborator = TicketCollaborator.query.filter_by(
        ticket_id=ticket_id,
        user_id=user_id
    ).first()
    
    if not collaborator:
        abort(404, description='Colaborador no encontrado en este ticket')
    
    # No permitir remover al asignado principal
    if ticket.assigned_to_user_id == user_id:
        abort(400, description='No se puede remover al técnico asignado principal')
    
    try:
        db.session.delete(collaborator)
        db.session.commit()
        logger.info(f'Colaborador {user_id} removido del ticket {ticket_id}')
    except Exception as e:
        db.session.rollback()
        logger.error(f'Error al remover colaborador: {e}')
        abort(500, description='Error al remover colaborador')


# ==================== ACTUALIZAR COLABORADOR ====================
def update_collaborator(
    ticket_id: int,
    user_id: int,
    time_invested_minutes: int = None,
    notes: str = None
) -> TicketCollaborator:
    """
    Actualiza el tiempo invertido y/o notas de un colaborador.
    
    Args:
        ticket_id: ID del ticket
        user_id: ID del colaborador
        time_invested_minutes: Nuevo tiempo (opcional)
        notes: Nuevas notas (opcional)
    
    Returns:
        TicketCollaborator actualizado
    
    Raises:
        404: Si el ticket o colaborador no existen
        400: Si el tiempo es negativo
    """
    # Buscar colaborador
    collaborator = TicketCollaborator.query.filter_by(
        ticket_id=ticket_id,
        user_id=user_id
    ).first()
    
    if not collaborator:
        abort(404, description='Colaborador no encontrado en este ticket')
    
    # Actualizar campos si se proporcionan
    if time_invested_minutes is not None:
        if time_invested_minutes < 0:
            abort(400, description='El tiempo invertido no puede ser negativo')
        collaborator.time_invested_minutes = time_invested_minutes
    
    if notes is not None:
        collaborator.notes = notes
    
    try:
        db.session.commit()
        logger.info(f'Colaborador {user_id} actualizado en ticket {ticket_id}')
        return collaborator
    except Exception as e:
        db.session.rollback()
        logger.error(f'Error al actualizar colaborador: {e}')
        abort(500, description='Error al actualizar colaborador')


# ==================== OBTENER COLABORADORES ====================
def get_ticket_collaborators(ticket_id: int) -> list[TicketCollaborator]:
    """
    Obtiene todos los colaboradores de un ticket.
    
    Args:
        ticket_id: ID del ticket
    
    Returns:
        Lista de TicketCollaborator ordenados por fecha
    
    Raises:
        404: Si el ticket no existe
    """
    # Validar ticket
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        abort(404, description='Ticket no encontrado')
    
    collaborators = (
        TicketCollaborator.query
        .filter_by(ticket_id=ticket_id)
        .order_by(TicketCollaborator.added_at.asc())
        .all()
    )
    
    return collaborators


# ==================== SUGERIR ROL ====================
def suggest_collaboration_role(user_id: int, ticket_id: int) -> str:
    """
    Sugiere un rol de colaboración basándose en el contexto del usuario y ticket.
    
    Args:
        user_id: ID del usuario
        ticket_id: ID del ticket
    
    Returns:
        Rol sugerido ('LEAD', 'SUPERVISOR', 'COLLABORATOR', 'TRAINEE', 'CONSULTANT')
    """
    user = User.query.get(user_id)
    if not user:
        return 'COLLABORATOR'
    
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        return 'COLLABORATOR'
    
    # Si es el asignado principal → LEAD
    if ticket.assigned_to_user_id == user_id:
        return 'LEAD'
    
    # Obtener roles del usuario en helpdesk
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    # Si es jefe de departamento o admin → SUPERVISOR
    if 'department_head' in user_roles or 'admin' in user_roles:
        return 'SUPERVISOR'
    
    # Si es residente o servicio social → TRAINEE
    if 'resident' in user_roles or 'social_service' in user_roles:
        return 'TRAINEE'
    
    # Si es técnico (desarrollo o soporte) → COLLABORATOR
    if 'tech_desarrollo' in user_roles or 'tech_soporte' in user_roles:
        return 'COLLABORATOR'
    
    # Default → CONSULTANT
    return 'CONSULTANT'


# ==================== TICKETS DONDE COLABORÉ ====================
def get_tickets_where_user_collaborated(
    user_id: int,
    page: int = 1,
    per_page: int = 20
) -> dict:
    """
    Obtiene tickets donde el usuario colaboró (incluyendo como asignado principal).
    
    Args:
        user_id: ID del usuario
        page: Número de página
        per_page: Items por página
    
    Returns:
        Dict con tickets, total, páginas, etc.
    """
    # Subquery de tickets donde colaboró
    collab_ticket_ids = (
        db.session.query(TicketCollaborator.ticket_id)
        .filter(TicketCollaborator.user_id == user_id)
        .subquery()
    )
    
    query = Ticket.query.filter(Ticket.id.in_(collab_ticket_ids))
    query = query.order_by(Ticket.created_at.desc())
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
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
def can_user_manage_collaborators(user_id: int, ticket_id: int) -> bool:
    """
    Verifica si un usuario puede gestionar colaboradores de un ticket.
    
    Args:
        user_id: ID del usuario
        ticket_id: ID del ticket
    
    Returns:
        True si puede gestionar, False si no
    """
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        return False
    
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    # Admin y secretaría pueden gestionar cualquier ticket
    if 'admin' in user_roles or 'secretary' in user_roles:
        return True
    
    # El técnico asignado puede gestionar sus propios tickets
    if ticket.assigned_to_user_id == user_id:
        return True
    
    return False


# ==================== ESTADÍSTICAS ====================
def get_user_collaboration_stats(user_id: int, days: int = 30) -> dict:
    """
    Obtiene estadísticas de colaboración de un usuario.
    
    Args:
        user_id: ID del usuario
        days: Número de días hacia atrás (default: 30)
    
    Returns:
        Dict con estadísticas
    """
    from datetime import datetime, timedelta
    
    start_date = datetime.now() - timedelta(days=days)
    
    # Total de tickets donde colaboró
    total_collaborations = (
        TicketCollaborator.query
        .filter(TicketCollaborator.user_id == user_id)
        .join(Ticket)
        .filter(Ticket.created_at >= start_date)
        .count()
    )
    
    # Por rol
    role_counts = {}
    for role in TicketCollaborator.VALID_ROLES:
        count = (
            TicketCollaborator.query
            .filter(
                TicketCollaborator.user_id == user_id,
                TicketCollaborator.collaboration_role == role
            )
            .join(Ticket)
            .filter(Ticket.created_at >= start_date)
            .count()
        )
        role_counts[role.lower()] = count
    
    # Tiempo total invertido
    total_time = (
        db.session.query(db.func.sum(TicketCollaborator.time_invested_minutes))
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