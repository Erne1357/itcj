from datetime import datetime
from flask import abort
from itcj.core.extensions import db
from itcj.apps.helpdesk.models import Ticket, Category, Comment, StatusLog
from itcj.apps.helpdesk.utils.ticket_number_generator import generate_ticket_number
from itcj.core.models.user import User
from itcj.core.models.department import Department
from sqlalchemy import and_, or_
import logging

logger = logging.getLogger(__name__)


# ==================== CREAR TICKET ====================
def create_ticket(
    requester_id: int,
    area: str,
    category_id: int,
    title: str,
    description: str,
    priority: str = 'MEDIA',
    location: str = None,
    office_folio: str = None
) -> Ticket:
    """
    Crea un nuevo ticket.
    
    Args:
        requester_id: ID del usuario que solicita
        area: 'DESARROLLO' o 'SOPORTE'
        category_id: ID de la categoría
        title: Título del ticket
        description: Descripción del problema
        priority: 'BAJA', 'MEDIA', 'ALTA', 'URGENTE'
        location: Ubicación física (opcional)
        office_folio: Folio de oficio (opcional)
    
    Returns:
        Ticket creado
    
    Raises:
        404: Si el usuario o categoría no existen
        400: Si los datos son inválidos
    """
    # Validar usuario
    requester = User.query.get(requester_id)
    if not requester:
        abort(404, description='Usuario no encontrado')
    
    # Validar categoría
    category = Category.query.get(category_id)
    if not category or not category.is_active:
        abort(400, description='Categoría inválida o inactiva')
    
    # Validar que la categoría corresponda al área
    if category.area != area:
        abort(400, description=f'La categoría no corresponde al área {area}')
    
    # Validar área
    if area not in ['DESARROLLO', 'SOPORTE']:
        abort(400, description='Área debe ser DESARROLLO o SOPORTE')
    
    # Validar prioridad
    if priority not in ['BAJA', 'MEDIA', 'ALTA', 'URGENTE']:
        abort(400, description='Prioridad inválida')
    
    # Obtener departamento del usuario (puede ser None)
    department_id = None
    try:
        # Intentar obtener el departamento del usuario vía positions
        from itcj.core.models.position import UserPosition
        user_position = UserPosition.query.filter_by(
            user_id=requester_id,
            is_active=True
        ).first()
        
        if user_position and user_position.position:
            department_id = user_position.position.department_id
    except Exception as e:
        logger.warning(f"No se pudo obtener departamento del usuario {requester_id}: {e}")
    
    # Generar número de ticket
    ticket_number = generate_ticket_number()
    
    # Crear ticket
    ticket = Ticket(
        ticket_number=ticket_number,
        requester_id=requester_id,
        requester_department_id=department_id,
        area=area,
        category_id=category_id,
        priority=priority,
        title=title,
        description=description,
        location=location,
        office_document_folio=office_folio,
        status='PENDING'
    )
    
    db.session.add(ticket)
    
    # Registrar creación en log
    status_log = StatusLog(
        ticket=ticket,
        from_status=None,
        to_status='PENDING',
        changed_by_id=requester_id,
        notes='Ticket creado'
    )
    db.session.add(status_log)
    
    try:
        db.session.commit()
        logger.info(f"Ticket {ticket.ticket_number} creado por usuario {requester_id}")
        return ticket
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al crear ticket: {e}")
        abort(500, description='Error al crear ticket')


# ==================== OBTENER TICKET ====================
def get_ticket_by_id(ticket_id: int, user_id: int = None, check_permissions: bool = True) -> Ticket:
    """
    Obtiene un ticket por ID con validación de permisos.
    
    Args:
        ticket_id: ID del ticket
        user_id: ID del usuario que consulta (para validar permisos)
        check_permissions: Si debe validar que el usuario pueda ver el ticket
    
    Returns:
        Ticket encontrado
    
    Raises:
        404: Si el ticket no existe
        403: Si el usuario no tiene permiso para verlo
    """
    ticket = Ticket.query.get(ticket_id)
    
    if not ticket:
        abort(404, description='Ticket no encontrado')
    
    # Validar permisos si se requiere
    if check_permissions and user_id:
        if not can_user_view_ticket(ticket, user_id):
            abort(403, description='No tienes permiso para ver este ticket')
    
    return ticket


# ==================== LISTAR TICKETS ====================
def list_tickets(
    user_id: int,
    user_roles: list[str],
    status = None,  # str o list[str]
    area: str = None,
    priority: str = None,
    assigned_to_me: bool = False,
    created_by_me: bool = False,
    department_id: int = None,
    page: int = 1,
    per_page: int = 20
) -> dict:
    """
    Lista tickets según filtros y permisos del usuario.
    
    Args:
        user_id: ID del usuario que consulta
        user_roles: Lista de roles del usuario en la app helpdesk
        status: Filtrar por estado (str) o múltiples estados (list[str])
        area: Filtrar por área (DESARROLLO/SOPORTE)
        priority: Filtrar por prioridad
        assigned_to_me: Solo tickets asignados a mí
        created_by_me: Solo tickets creados por mí
        department_id: Solo tickets de un departamento
        page: Página actual
        per_page: Tickets por página
    
    Returns:
        Dict con tickets, total, páginas, etc.
    """
    query = Ticket.query
    
    # PERMISOS: Determinar qué tickets puede ver
    if 'admin' in user_roles or 'secretary' in user_roles:
        # Admin y secretaría ven todos
        pass
    elif 'tech_desarrollo' in user_roles or 'tech_soporte' in user_roles:
        # Técnicos solo ven tickets asignados a ellos o a su equipo
        tech_area = 'desarrollo' if 'tech_desarrollo' in user_roles else 'soporte'
        query = query.filter(
            or_(
                Ticket.assigned_to_user_id == user_id,
                Ticket.assigned_to_team == tech_area
            )
        )
    elif 'department_head' in user_roles:
        # Jefe de departamento solo ve tickets de su departamento
        # Obtener departamento del usuario
        from itcj.core.models.position import UserPosition
        user_position = UserPosition.query.filter_by(
            user_id=user_id,
            is_active=True
        ).first()
        
        if user_position and user_position.position:
            query = query.filter(Ticket.requester_department_id == user_position.position.department_id)
        else:
            # Si no tiene departamento, no ve nada
            query = query.filter(Ticket.id == -1)
    else:
        # Usuario regular: solo sus propios tickets
        query = query.filter(Ticket.requester_id == user_id)
    
    # FILTROS ADICIONALES
    if status:
        # Manejar múltiples estados
        if isinstance(status, list):
            if len(status) == 1:
                query = query.filter(Ticket.status == status[0])
            else:
                query = query.filter(Ticket.status.in_(status))
        else:
            # Status individual (string)
            query = query.filter(Ticket.status == status)
    
    if area:
        query = query.filter(Ticket.area == area)
    
    if priority:
        query = query.filter(Ticket.priority == priority)
    
    if assigned_to_me:
        query = query.filter(Ticket.assigned_to_user_id == user_id)
    
    if created_by_me:
        query = query.filter(Ticket.requester_id == user_id)
    
    if department_id:
        query = query.filter(Ticket.requester_department_id == department_id)
    
    # ORDENAMIENTO: Prioridad + FIFO (created_at)
    priority_order = db.case(
        (Ticket.priority == 'URGENTE', 1),
        (Ticket.priority == 'ALTA', 2),
        (Ticket.priority == 'MEDIA', 3),
        (Ticket.priority == 'BAJA', 4),
        else_=5
    )
    query = query.order_by(priority_order, Ticket.created_at.asc())
    
    # PAGINACIÓN
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


# ==================== CAMBIAR ESTADO ====================
def change_status(
    ticket_id: int,
    new_status: str,
    changed_by_id: int,
    notes: str = None
) -> Ticket:
    """
    Cambia el estado de un ticket y registra en el log.
    
    Args:
        ticket_id: ID del ticket
        new_status: Nuevo estado
        changed_by_id: ID del usuario que hace el cambio
        notes: Notas del cambio (opcional)
    
    Returns:
        Ticket actualizado
    
    Raises:
        404: Si el ticket no existe
        400: Si el cambio de estado es inválido
    """
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        abort(404, description='Ticket no encontrado')
    
    # Validar estados válidos
    valid_statuses = ['PENDING', 'ASSIGNED', 'IN_PROGRESS', 'RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED', 'CANCELED']
    if new_status not in valid_statuses:
        abort(400, description='Estado inválido')
    
    # Guardar estado anterior
    old_status = ticket.status
    
    # Validar transiciones de estado
    if not _is_valid_status_transition(old_status, new_status):
        abort(400, description=f'Transición inválida de {old_status} a {new_status}')
    
    # Cambiar estado
    ticket.status = new_status
    ticket.updated_at = datetime.utcnow()
    
    # Si se cierra, guardar fecha
    if new_status == 'CLOSED':
        ticket.closed_at = datetime.utcnow()
    
    # Registrar en log
    status_log = StatusLog(
        ticket_id=ticket_id,
        from_status=old_status,
        to_status=new_status,
        changed_by_id=changed_by_id,
        notes=notes
    )
    db.session.add(status_log)
    
    try:
        db.session.commit()
        logger.info(f"Ticket {ticket.ticket_number} cambió de {old_status} a {new_status}")
        return ticket
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al cambiar estado del ticket: {e}")
        abort(500, description='Error al cambiar estado')


# ==================== RESOLVER TICKET ====================
def resolve_ticket(
    ticket_id: int,
    resolved_by_id: int,
    success: bool,
    resolution_notes: str,
    time_invested_minutes: int = None
) -> Ticket:
    """
    Marca un ticket como resuelto.
    
    Args:
        ticket_id: ID del ticket
        resolved_by_id: ID del técnico que resuelve
        success: True si fue exitoso, False si no se pudo resolver
        resolution_notes: Notas de la resolución
        time_invested_minutes: Tiempo invertido por el técnico (opcional)
    
    Returns:
        Ticket resuelto
    
    Raises:
        404: Si el ticket no existe
        400: Si el ticket no puede ser resuelto
    """
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        abort(404, description='Ticket no encontrado')
    
    # Validar que esté en un estado resolvible
    if ticket.status not in ['ASSIGNED', 'IN_PROGRESS']:
        abort(400, description='El ticket no puede ser resuelto en su estado actual')
    
    # Validar notas de resolución
    if not resolution_notes or len(resolution_notes.strip()) < 10:
        abort(400, description='Las notas de resolución deben tener al menos 10 caracteres')
    
    # Actualizar ticket
    new_status = 'RESOLVED_SUCCESS' if success else 'RESOLVED_FAILED'
    ticket.status = new_status
    ticket.resolution_notes = resolution_notes
    ticket.resolved_at = datetime.utcnow()
    ticket.resolved_by_id = resolved_by_id
    ticket.updated_at = datetime.utcnow()
    
    # Guardar tiempo invertido si se proporcionó
    if time_invested_minutes is not None:
        if time_invested_minutes < 0:
            abort(400, description='El tiempo invertido no puede ser negativo')
        ticket.time_invested_minutes = time_invested_minutes
    
    # Registrar en log
    status_log = StatusLog(
        ticket_id=ticket_id,
        from_status=ticket.status,
        to_status=new_status,
        changed_by_id=resolved_by_id,
        notes=f'Ticket resuelto: {resolution_notes[:100]}'
    )
    db.session.add(status_log)
    
    # Marcar attachments para auto-eliminación (si los hay)
    try:
        for attachment in ticket.attachments:
            if not attachment.auto_delete_at:
                attachment.set_auto_delete(days=7)
    except Exception as e:
        logger.warning(f"Error al marcar attachments para eliminación: {e}")
    
    try:
        db.session.commit()
        logger.info(f"Ticket {ticket.ticket_number} resuelto por usuario {resolved_by_id}")
        return ticket
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al resolver ticket: {e}")
        abort(500, description='Error al resolver ticket')


# ==================== CALIFICAR TICKET ====================
def rate_ticket(
    ticket_id: int,
    requester_id: int,
    rating: int,
    comment: str = None
) -> Ticket:
    """
    Usuario califica el servicio del ticket.
    
    Args:
        ticket_id: ID del ticket
        requester_id: ID del usuario que califica (debe ser el requester)
        rating: Calificación de 1 a 5
        comment: Comentario opcional
    
    Returns:
        Ticket calificado
    
    Raises:
        404: Si el ticket no existe
        403: Si el usuario no es el requester
        400: Si el ticket no puede ser calificado
    """
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        abort(404, description='Ticket no encontrado')
    
    # Validar que sea el requester
    if ticket.requester_id != requester_id:
        abort(403, description='Solo el solicitante puede calificar')
    
    # Validar que esté resuelto
    if ticket.status not in ['RESOLVED_SUCCESS', 'RESOLVED_FAILED']:
        abort(400, description='Solo se pueden calificar tickets resueltos')
    
    # Validar que no haya sido calificado antes
    if ticket.rating is not None:
        abort(400, description='Este ticket ya fue calificado')
    
    # Validar rango de calificación
    if not isinstance(rating, int) or rating < 1 or rating > 5:
        abort(400, description='La calificación debe ser entre 1 y 5')
    
    # Actualizar ticket
    ticket.rating = rating
    ticket.rating_comment = comment
    ticket.rated_at = datetime.utcnow()
    ticket.status = 'CLOSED'
    ticket.closed_at = datetime.utcnow()
    ticket.updated_at = datetime.utcnow()
    
    # Registrar en log
    status_log = StatusLog(
        ticket_id=ticket_id,
        from_status='RESOLVED_SUCCESS' if ticket.status == 'CLOSED' else 'RESOLVED_FAILED',
        to_status='CLOSED',
        changed_by_id=requester_id,
        notes=f'Ticket calificado con {rating} estrellas'
    )
    db.session.add(status_log)
    
    try:
        db.session.commit()
        logger.info(f"Ticket {ticket.ticket_number} calificado con {rating} estrellas")
        return ticket
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al calificar ticket: {e}")
        abort(500, description='Error al calificar ticket')


# ==================== CANCELAR TICKET ====================
def cancel_ticket(ticket_id: int, user_id: int, reason: str = None) -> Ticket:
    """
    Usuario cancela su ticket.
    
    Args:
        ticket_id: ID del ticket
        user_id: ID del usuario que cancela (debe ser el requester)
        reason: Razón de cancelación (opcional)
    
    Returns:
        Ticket cancelado
    
    Raises:
        404: Si el ticket no existe
        403: Si el usuario no es el requester
        400: Si el ticket no puede ser cancelado
    """
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        abort(404, description='Ticket no encontrado')
    
    # Validar que sea el requester
    if ticket.requester_id != user_id:
        abort(403, description='Solo el solicitante puede cancelar')
    
    # Validar que no esté ya resuelto o cerrado
    if ticket.status in ['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED', 'CANCELED']:
        abort(400, description='No se puede cancelar un ticket ya resuelto o cerrado')
    
    # Cancelar ticket
    old_status = ticket.status
    ticket.status = 'CANCELED'
    ticket.closed_at = datetime.utcnow()
    ticket.updated_at = datetime.utcnow()
    
    # Registrar en log
    status_log = StatusLog(
        ticket_id=ticket_id,
        from_status=old_status,
        to_status='CANCELED',
        changed_by_id=user_id,
        notes=f'Ticket cancelado: {reason}' if reason else 'Ticket cancelado'
    )
    db.session.add(status_log)
    
    try:
        db.session.commit()
        logger.info(f"Ticket {ticket.ticket_number} cancelado por usuario {user_id}")
        return ticket
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al cancelar ticket: {e}")
        abort(500, description='Error al cancelar ticket')


# ==================== AGREGAR COMENTARIO ====================
def add_comment(
    ticket_id: int,
    author_id: int,
    content: str,
    is_internal: bool = False
) -> Comment:
    """
    Agrega un comentario a un ticket.
    
    Args:
        ticket_id: ID del ticket
        author_id: ID del usuario que comenta
        content: Contenido del comentario
        is_internal: Si es un comentario interno (solo staff)
    
    Returns:
        Comentario creado
    
    Raises:
        404: Si el ticket no existe
        400: Si el contenido es inválido
    """
    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        abort(404, description='Ticket no encontrado')
    
    # Validar contenido
    if not content or len(content.strip()) < 3:
        abort(400, description='El comentario debe tener al menos 3 caracteres')
    
    # Crear comentario
    comment = Comment(
        ticket_id=ticket_id,
        author_id=author_id,
        content=content.strip(),
        is_internal=is_internal
    )
    
    db.session.add(comment)
    ticket.updated_at = datetime.utcnow()
    
    try:
        db.session.commit()
        logger.info(f"Comentario agregado al ticket {ticket.ticket_number}")
        return comment
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error al agregar comentario: {e}")
        abort(500, description='Error al agregar comentario')


# ==================== FUNCIONES AUXILIARES ====================
def can_user_view_ticket(ticket: Ticket, user_id: int) -> bool:
    """
    Verifica si un usuario puede ver un ticket específico.
    
    Args:
        ticket: Ticket a verificar
        user_id: ID del usuario
    
    Returns:
        True si puede ver, False si no
    """
    from itcj.core.services.authz_service import user_roles_in_app
    
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    # Admin y secretaría ven todo
    if 'admin' in user_roles or 'secretary' in user_roles:
        return True
    
    # Requester ve su ticket
    if ticket.requester_id == user_id:
        return True
    
    # Técnico asignado ve su ticket
    if ticket.assigned_to_user_id == user_id:
        return True
    
    # Jefe de departamento ve tickets de su departamento
    if 'department_head' in user_roles:
        from itcj.core.models.position import UserPosition
        user_position = UserPosition.query.filter_by(
            user_id=user_id,
            is_active=True
        ).first()
        
        if user_position and user_position.position:
            if ticket.requester_department_id == user_position.position.department_id:
                return True
    
    return False


def _is_valid_status_transition(from_status: str, to_status: str) -> bool:
    """
    Valida si una transición de estado es válida.
    
    Args:
        from_status: Estado actual
        to_status: Estado nuevo
    
    Returns:
        True si es válida, False si no
    """
    # Transiciones válidas
    valid_transitions = {
        'PENDING': ['ASSIGNED', 'CANCELED'],
        'ASSIGNED': ['IN_PROGRESS', 'PENDING', 'CANCELED'],
        'IN_PROGRESS': ['ASSIGNED', 'RESOLVED_SUCCESS', 'RESOLVED_FAILED'],
        'RESOLVED_SUCCESS': ['CLOSED'],
        'RESOLVED_FAILED': ['CLOSED', 'ASSIGNED'],
        'CLOSED': [],  # No se puede cambiar desde cerrado
        'CANCELED': []  # No se puede cambiar desde cancelado
    }
    
    return to_status in valid_transitions.get(from_status, [])