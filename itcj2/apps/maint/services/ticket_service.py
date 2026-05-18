import logging
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from itcj2.apps.maint.models.ticket import MaintTicket, SLA_HOURS  # SLA_HOURS se mantiene como fallback
from itcj2.apps.maint.utils.catalog_cache import get_priority_codes, get_sla_hours
from itcj2.apps.maint.models.category import MaintCategory
from itcj2.apps.maint.models.comment import MaintComment
from itcj2.apps.maint.models.status_log import MaintStatusLog
from itcj2.apps.maint.models.action_log import MaintTicketActionLog
from itcj2.apps.maint.utils.ticket_number_generator import generate_ticket_number
from itcj2.apps.maint.utils.timezone_utils import now_local, ensure_local_timezone
from itcj2.core.models.user import User
from itcj2.models.base import paginate

logger = logging.getLogger(__name__)


# ==================== CREAR TICKET ====================

def create_ticket(
    db: Session,
    requester_id: int,
    category_id: int,
    title: str,
    description: str,
    priority: str = 'MEDIA',
    location: str = None,
    custom_fields: dict = None,
    created_by_id: int = None,
    department_id: int = None,
) -> MaintTicket:
    """
    Crea un nuevo ticket de mantenimiento.
    Calcula due_at según la prioridad (SLA_HOURS).

    department_id: si viene, se valida que el solicitante tenga ese depto via
    UserPosition activa. Si no viene, se resuelve automáticamente: si tiene
    un solo depto activo, se usa; si tiene varios, se requiere selección
    explícita (HTTP 400).
    """
    valid_codes = get_priority_codes()
    if priority not in valid_codes:
        raise HTTPException(
            status_code=400,
            detail=f'Prioridad inválida. Valores permitidos: {", ".join(sorted(valid_codes))}',
        )

    requester = db.get(User, requester_id)
    if not requester:
        raise HTTPException(status_code=404, detail='Usuario no encontrado')

    category = db.get(MaintCategory, category_id)
    if not category or not category.is_active:
        raise HTTPException(status_code=400, detail='Categoría inválida o inactiva')

    # Determinar/validar departamento del solicitante via puestos activos
    from itcj2.core.models.position import UserPosition, Position
    user_depts = (
        db.query(Position.department_id)
        .join(UserPosition, UserPosition.position_id == Position.id)
        .filter(
            UserPosition.user_id == requester_id,
            UserPosition.is_active == True,
            Position.department_id.isnot(None),
        )
        .distinct()
        .all()
    )
    user_dept_ids = {r[0] for r in user_depts}

    if department_id is not None:
        if department_id not in user_dept_ids:
            raise HTTPException(
                status_code=400,
                detail='El departamento indicado no corresponde a un puesto activo del solicitante.',
            )
    elif len(user_dept_ids) == 1:
        department_id = next(iter(user_dept_ids))
    elif len(user_dept_ids) > 1:
        raise HTTPException(
            status_code=400,
            detail='El solicitante pertenece a varios departamentos; debes indicar `department_id` explícitamente.',
        )
    # else: ningún depto — department_id queda None (no bloquea, queda nulo en BD)

    # Restricción: máximo 3 tickets sin calificar
    unrated = db.query(MaintTicket).filter(
        MaintTicket.requester_id == requester_id,
        MaintTicket.status.in_(['RESOLVED_SUCCESS', 'RESOLVED_FAILED']),
        MaintTicket.rating_attention.is_(None),
    ).count()
    if unrated >= 3:
        raise HTTPException(
            status_code=400,
            detail='Tienes 3 o más solicitudes resueltas sin calificar. Por favor califica tus solicitudes anteriores antes de crear una nueva.',
        )

    ticket_number = generate_ticket_number(db)
    created_by = created_by_id or requester_id
    now = now_local()
    due_at = now + timedelta(hours=get_sla_hours(priority))

    ticket = MaintTicket(
        ticket_number=ticket_number,
        requester_id=requester_id,
        requester_department_id=department_id,
        category_id=category_id,
        priority=priority,
        title=title.strip(),
        description=description.strip(),
        location=location.strip() if location else None,
        custom_fields=custom_fields or {},
        status='PENDING',
        due_at=due_at,
        created_by_id=created_by,
        updated_by_id=created_by,
    )
    db.add(ticket)
    db.flush()

    db.add(MaintStatusLog(
        ticket=ticket,
        from_status=None,
        to_status='PENDING',
        changed_by_id=created_by,
        notes='Ticket creado',
    ))
    db.add(MaintTicketActionLog(
        ticket=ticket,
        action='CREATED',
        performed_by_id=created_by,
        detail={'ticket_number': ticket_number},
    ))

    try:
        db.commit()
        logger.info(f"Ticket {ticket.ticket_number} creado por usuario {requester_id}, due_at: {due_at}")
        return ticket
    except Exception as e:
        db.rollback()
        logger.error(f"Error al crear ticket de maint: {e}")
        raise HTTPException(status_code=500, detail='Error al crear ticket')


# ==================== OBTENER TICKET ====================

def get_ticket_by_id(db: Session, ticket_id: int, user_id: int = None) -> MaintTicket:
    ticket = db.get(MaintTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')
    if user_id and not can_user_view_ticket(db, ticket, user_id):
        raise HTTPException(status_code=403, detail='No tienes permiso para ver este ticket')
    return ticket


# ==================== LISTAR TICKETS ====================

def list_tickets(
    db: Session,
    user_id: int,
    user_roles: list,
    department_id: int = None,
    status=None,
    category_id: int = None,
    priority: str = None,
    search: str = None,
    page: int = 1,
    per_page: int = 20,
    assigned_to_me: bool = False,
) -> dict:
    """
    Lista tickets según el rol del usuario:
    - admin / dispatcher / tech_maint → todos
    - department_head / secretary    → solo su departamento
    - staff / any other              → solo propios

    `assigned_to_me`: filtro adicional que limita a tickets donde el user
    es técnico activo asignado (cross-cutting con el scope del rol).
    Ordenado siempre por `created_at DESC` (LIFO).
    """
    query = db.query(MaintTicket)

    FULL_ACCESS_ROLES = {'admin', 'dispatcher', 'tech_maint'}
    DEPT_ACCESS_ROLES = {'department_head', 'secretary'}

    if FULL_ACCESS_ROLES & set(user_roles):
        pass  # Sin restricción
    elif DEPT_ACCESS_ROLES & set(user_roles):
        dept_id = department_id
        if not dept_id:
            try:
                from itcj2.core.models.position import UserPosition
                up = db.query(UserPosition).filter_by(user_id=user_id, is_active=True).first()
                if up and up.position:
                    dept_id = up.position.department_id
            except Exception:
                pass
        if dept_id:
            query = query.filter(MaintTicket.requester_department_id == dept_id)
        else:
            query = query.filter(MaintTicket.id == -1)
    else:
        query = query.filter(MaintTicket.requester_id == user_id)

    if status:
        if isinstance(status, list):
            query = query.filter(MaintTicket.status.in_(status))
        else:
            query = query.filter(MaintTicket.status == status)

    if category_id:
        query = query.filter(MaintTicket.category_id == category_id)

    if priority:
        query = query.filter(MaintTicket.priority == priority)

    if search:
        term = f"%{search}%"
        query = query.filter(or_(
            MaintTicket.title.ilike(term),
            MaintTicket.ticket_number.ilike(term),
            MaintTicket.description.ilike(term),
        ))

    if assigned_to_me:
        # Solo tickets con técnico activo (unassigned_at NULL) = user actual.
        from itcj2.apps.maint.models import MaintTicketTechnician
        query = query.filter(
            MaintTicket.id.in_(
                db.query(MaintTicketTechnician.ticket_id).filter(
                    MaintTicketTechnician.user_id == user_id,
                    MaintTicketTechnician.unassigned_at.is_(None),
                )
            )
        )

    query = query.order_by(MaintTicket.created_at.desc())
    pagination = paginate(query, page=page, per_page=per_page)

    return {
        'tickets': pagination.items,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page,
        'per_page': per_page,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev,
    }


# ==================== EDITAR TICKET PENDIENTE ====================

def update_pending_ticket(
    db: Session,
    ticket_id: int,
    updated_by_id: int,
    category_id: int = None,
    priority: str = None,
    title: str = None,
    description: str = None,
    location: str = None,
    custom_fields: dict = None,
) -> MaintTicket:
    """Solo se pueden editar tickets en estado PENDING."""
    ticket = db.get(MaintTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    if ticket.status != 'PENDING':
        raise HTTPException(status_code=400, detail='Solo se pueden editar tickets en estado PENDING')

    if category_id and category_id != ticket.category_id:
        category = db.get(MaintCategory, category_id)
        if not category or not category.is_active:
            raise HTTPException(status_code=400, detail='Categoría inválida o inactiva')
        ticket.category_id = category_id
        ticket.custom_fields = {}  # Limpiar campos dinámicos al cambiar categoría

    if priority and priority != ticket.priority:
        valid_codes = get_priority_codes()
        if priority not in valid_codes:
            raise HTTPException(
                status_code=400,
                detail=f'Prioridad inválida. Valores permitidos: {", ".join(sorted(valid_codes))}',
            )
        ticket.priority = priority
        # Recalcular due_at con la nueva prioridad
        ticket.due_at = now_local() + timedelta(hours=get_sla_hours(priority))

    if title is not None:
        ticket.title = title.strip()

    if description is not None:
        ticket.description = description.strip()

    if location is not None:
        ticket.location = location.strip() if location.strip() else None

    if custom_fields is not None:
        ticket.custom_fields = custom_fields

    ticket.updated_at = now_local()
    ticket.updated_by_id = updated_by_id

    db.add(MaintTicketActionLog(
        ticket_id=ticket_id,
        action='EDITED',
        performed_by_id=updated_by_id,
    ))

    try:
        db.commit()
        logger.info(f"Ticket {ticket.ticket_number} editado por usuario {updated_by_id}")
        return ticket
    except Exception as e:
        db.rollback()
        logger.error(f"Error al editar ticket maint: {e}")
        raise HTTPException(status_code=500, detail='Error al editar ticket')


# ==================== RESOLVER TICKET ====================

def resolve_ticket(
    db: Session,
    ticket_id: int,
    resolved_by_id: int,
    success: bool,
    maintenance_type: str,
    service_origin: str,
    resolution_notes: str,
    time_invested_minutes: int,
    observations: str = None,
    materials_used: list = None,
) -> tuple:
    """
    Resuelve el ticket. El resolutor puede ser:
    - Un técnico activamente asignado → acción RESOLVED_BY_ASSIGNED
    - Cualquier dispatcher            → acción RESOLVED_BY_DISPATCHER
    La validación de quién puede resolver se hace en la capa API (con los permisos).
    """
    ticket = db.get(MaintTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    if ticket.status not in ('ASSIGNED', 'IN_PROGRESS'):
        raise HTTPException(status_code=400, detail='El ticket no puede ser resuelto en su estado actual')

    if maintenance_type not in ('PREVENTIVO', 'CORRECTIVO'):
        raise HTTPException(status_code=400, detail='Tipo de mantenimiento inválido (PREVENTIVO o CORRECTIVO)')

    if service_origin not in ('INTERNO', 'EXTERNO'):
        raise HTTPException(status_code=400, detail='Origen del servicio inválido (INTERNO o EXTERNO)')

    # Determinar si es técnico asignado o dispatcher
    is_assigned_tech = any(
        t.user_id == resolved_by_id and t.unassigned_at is None
        for t in ticket.technicians
    )
    action = 'RESOLVED_BY_ASSIGNED' if is_assigned_tech else 'RESOLVED_BY_DISPATCHER'

    new_status = 'RESOLVED_SUCCESS' if success else 'RESOLVED_FAILED'
    old_status = ticket.status
    now = now_local()

    ticket.status = new_status
    ticket.maintenance_type = maintenance_type
    ticket.service_origin = service_origin
    ticket.resolution_notes = resolution_notes.strip()
    ticket.time_invested_minutes = time_invested_minutes
    ticket.observations = observations.strip() if observations else None
    ticket.resolved_at = now
    ticket.resolved_by_id = resolved_by_id
    ticket.updated_at = now
    ticket.updated_by_id = resolved_by_id

    db.add(MaintStatusLog(
        ticket_id=ticket_id,
        from_status=old_status,
        to_status=new_status,
        changed_by_id=resolved_by_id,
        notes=resolution_notes[:200],
    ))
    db.add(MaintTicketActionLog(
        ticket_id=ticket_id,
        action=action,
        performed_by_id=resolved_by_id,
        detail={
            'success': success,
            'maintenance_type': maintenance_type,
            'service_origin': service_origin,
        },
    ))

    # ── Consumo de materiales del almacén (soft-fail) ─────────────────────
    warehouse_warnings = []
    if materials_used:
        from itcj2.apps.warehouse.services import fifo_service
        for mat in materials_used:
            sp = db.begin_nested()
            try:
                fifo_service.consume(
                    db=db,
                    product_id=mat.product_id,
                    quantity=mat.quantity,
                    source_app='maint',
                    source_ticket_id=ticket_id,
                    performed_by_id=resolved_by_id,
                    notes=mat.notes,
                )
                db.add(MaintTicketActionLog(
                    ticket_id=ticket_id,
                    action='WAREHOUSE_MATERIAL_ADDED',
                    performed_by_id=resolved_by_id,
                    detail={'product_id': mat.product_id, 'quantity': str(mat.quantity)},
                ))
                sp.commit()
            except Exception as mat_err:
                sp.rollback()
                if hasattr(mat_err, 'detail') and isinstance(mat_err.detail, dict):
                    msg = mat_err.detail.get('message', str(mat_err))
                elif hasattr(mat_err, 'detail') and isinstance(mat_err.detail, str):
                    msg = mat_err.detail
                else:
                    msg = str(mat_err)
                warehouse_warnings.append(msg)
                logger.warning(
                    "[maint] Warehouse consume failed for ticket %s product %s: %s",
                    ticket_id, mat.product_id, msg,
                )

    try:
        db.commit()
        logger.info(f"Ticket {ticket.ticket_number} resuelto ({action}) por usuario {resolved_by_id}")
        return ticket, warehouse_warnings
    except Exception as e:
        db.rollback()
        logger.error(f"Error al resolver ticket maint: {e}")
        raise HTTPException(status_code=500, detail='Error al resolver ticket')


# ==================== CALIFICAR TICKET ====================

def rate_ticket(
    db: Session,
    ticket_id: int,
    requester_id: int,
    rating_attention: int,
    rating_speed: int,
    rating_efficiency: bool,
    comment: str = None,
) -> MaintTicket:
    ticket = db.get(MaintTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    if ticket.requester_id != requester_id:
        raise HTTPException(status_code=403, detail='Solo el solicitante puede calificar')

    if ticket.status not in ('RESOLVED_SUCCESS', 'RESOLVED_FAILED'):
        raise HTTPException(status_code=400, detail='Solo se pueden calificar tickets resueltos')

    if ticket.rating_attention is not None:
        raise HTTPException(status_code=400, detail='Este ticket ya fue calificado')

    old_status = ticket.status
    now = now_local()

    ticket.rating_attention = rating_attention
    ticket.rating_speed = rating_speed
    ticket.rating_efficiency = rating_efficiency
    ticket.rating_comment = comment
    ticket.rated_at = now
    ticket.status = 'CLOSED'
    ticket.closed_at = now
    ticket.updated_at = now
    ticket.updated_by_id = requester_id

    db.add(MaintStatusLog(
        ticket_id=ticket_id,
        from_status=old_status,
        to_status='CLOSED',
        changed_by_id=requester_id,
        notes=f'Calificado — Atención: {rating_attention}/5, Rapidez: {rating_speed}/5',
    ))
    db.add(MaintTicketActionLog(
        ticket_id=ticket_id,
        action='RATED',
        performed_by_id=requester_id,
        detail={
            'rating_attention': rating_attention,
            'rating_speed': rating_speed,
            'rating_efficiency': rating_efficiency,
        },
    ))

    try:
        db.commit()
        logger.info(f"Ticket {ticket.ticket_number} calificado por usuario {requester_id}")
        return ticket
    except Exception as e:
        db.rollback()
        logger.error(f"Error al calificar ticket maint: {e}")
        raise HTTPException(status_code=500, detail='Error al calificar ticket')


# ==================== CANCELAR TICKET ====================

def cancel_ticket(
    db: Session,
    ticket_id: int,
    user_id: int,
    reason: str = None,
    user_roles: list = None,
) -> MaintTicket:
    ticket = db.get(MaintTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    roles = set(user_roles or [])
    is_privileged = bool(roles & {'admin', 'dispatcher'})

    # Verificar permiso para cancelar
    if not is_privileged and ticket.requester_id != user_id:
        raise HTTPException(status_code=403, detail='No tienes permiso para cancelar este ticket')

    if not ticket.is_open:
        raise HTTPException(status_code=400, detail='No se puede cancelar un ticket ya cerrado o cancelado')

    if ticket.status in ('RESOLVED_SUCCESS', 'RESOLVED_FAILED'):
        raise HTTPException(status_code=400, detail='No se puede cancelar un ticket ya resuelto')

    # Solicitante solo puede cancelar tickets PENDING
    if not is_privileged and ticket.status != 'PENDING':
        raise HTTPException(status_code=400, detail='Solo puedes cancelar tus solicitudes en estado Pendiente')

    old_status = ticket.status
    now = now_local()

    ticket.status = 'CANCELED'
    ticket.canceled_at = now
    ticket.canceled_by_id = user_id
    ticket.cancel_reason = reason
    ticket.updated_at = now
    ticket.updated_by_id = user_id

    db.add(MaintStatusLog(
        ticket_id=ticket_id,
        from_status=old_status,
        to_status='CANCELED',
        changed_by_id=user_id,
        notes=f'Cancelado: {reason}' if reason else 'Cancelado',
    ))
    db.add(MaintTicketActionLog(
        ticket_id=ticket_id,
        action='CANCELED',
        performed_by_id=user_id,
        detail={'reason': reason} if reason else None,
    ))

    try:
        db.commit()
        logger.info(f"Ticket {ticket.ticket_number} cancelado por usuario {user_id}")
        return ticket
    except Exception as e:
        db.rollback()
        logger.error(f"Error al cancelar ticket maint: {e}")
        raise HTTPException(status_code=500, detail='Error al cancelar ticket')


# ==================== AGREGAR COMENTARIO ====================

def add_comment(
    db: Session,
    ticket_id: int,
    author_id: int,
    content: str,
    is_internal: bool = False,
) -> MaintComment:
    ticket = db.get(MaintTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    if not ticket.is_open:
        raise HTTPException(status_code=400, detail='No se pueden agregar comentarios a tickets cerrados')

    comment = MaintComment(
        ticket_id=ticket_id,
        author_id=author_id,
        content=content.strip(),
        is_internal=is_internal,
    )
    db.add(comment)
    db.add(MaintTicketActionLog(
        ticket_id=ticket_id,
        action='COMMENTED',
        performed_by_id=author_id,
        detail={'is_internal': is_internal},
    ))

    ticket.updated_at = now_local()
    ticket.updated_by_id = author_id

    try:
        db.commit()
        logger.info(f"Comentario agregado al ticket {ticket.ticket_number}")
        return comment
    except Exception as e:
        db.rollback()
        logger.error(f"Error al agregar comentario: {e}")
        raise HTTPException(status_code=500, detail='Error al agregar comentario')


# ==================== AUXILIARES ====================

def can_user_view_ticket(db: Session, ticket: MaintTicket, user_id: int) -> bool:
    from itcj2.core.services.authz_service import user_roles_in_app

    roles = set(user_roles_in_app(db, user_id, 'maint'))

    # Acceso total
    if roles & {'admin', 'dispatcher', 'tech_maint'}:
        return True

    # Propio
    if ticket.requester_id == user_id:
        return True

    # Técnico asignado activo
    if any(t.user_id == user_id and t.unassigned_at is None for t in ticket.technicians):
        return True

    # Jefe/secretaria de departamento
    if roles & {'department_head', 'secretary'}:
        try:
            from itcj2.core.models.position import UserPosition
            up = db.query(UserPosition).filter_by(user_id=user_id, is_active=True).first()
            if up and up.position and ticket.requester_department_id == up.position.department_id:
                return True
        except Exception:
            pass

    return False


# ==================== INICIAR PROGRESO ====================

def start_progress(
    db: Session,
    ticket_id: int,
    user_id: int,
    user_roles: list = None,
) -> MaintTicket:
    """Cambia el estado de ASSIGNED → IN_PROGRESS."""
    ticket = db.get(MaintTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    if ticket.status != 'ASSIGNED':
        raise HTTPException(status_code=400, detail='Solo se puede iniciar progreso desde el estado Asignado')

    roles = set(user_roles or [])
    is_active_tech = any(t.user_id == user_id and t.unassigned_at is None for t in ticket.technicians)
    can_start = is_active_tech or bool(roles & {'dispatcher', 'admin'})
    if not can_start:
        raise HTTPException(status_code=403, detail='Solo los técnicos asignados o dispatchers pueden iniciar progreso')

    old_status = ticket.status
    now = now_local()
    ticket.status = 'IN_PROGRESS'
    ticket.updated_at = now
    ticket.updated_by_id = user_id

    db.add(MaintStatusLog(
        ticket_id=ticket_id,
        from_status=old_status,
        to_status='IN_PROGRESS',
        changed_by_id=user_id,
    ))
    db.add(MaintTicketActionLog(
        ticket_id=ticket_id,
        action='STATUS_CHANGED',
        performed_by_id=user_id,
        detail={'from_status': old_status, 'to_status': 'IN_PROGRESS'},
    ))

    try:
        db.commit()
        logger.info(f"Ticket {ticket.ticket_number} → IN_PROGRESS por usuario {user_id}")
        return ticket
    except Exception as e:
        db.rollback()
        logger.error(f"Error al iniciar progreso: {e}")
        raise HTTPException(status_code=500, detail='Error al actualizar estado')


# ==================== SERIALIZACIÓN ====================

def _dt(val):
    """Serializa un datetime a string ISO, o None."""
    return val.isoformat() if val else None


def serialize_ticket_summary(ticket: MaintTicket) -> dict:
    """Datos mínimos para la lista de tickets."""
    now = now_local()
    due_at_local = ensure_local_timezone(ticket.due_at) if ticket.due_at else None

    try:
        cat = {
            "id": ticket.category.id,
            "code": ticket.category.code,
            "name": ticket.category.name,
            "icon": ticket.category.icon,
            "field_template": ticket.category.field_template or [],
        } if ticket.category else None
    except Exception:
        cat = None

    try:
        req = {
            "id": ticket.requester.id,
            "name": ticket.requester.full_name,
            "email": getattr(ticket.requester, "email", None),
        }
    except Exception:
        req = {"id": ticket.requester_id, "name": "—", "email": None}

    try:
        active_techs = [
            {"id": t.user_id, "name": t.user.full_name if t.user else str(t.user_id)}
            for t in ticket.active_technicians
        ]
    except Exception:
        active_techs = []

    return {
        "id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "title": ticket.title,
        "status": ticket.status,
        "priority": ticket.priority,
        "progress_pct": ticket.progress_pct,
        "location": ticket.location,
        "due_at": _dt(ticket.due_at),
        "created_at": _dt(ticket.created_at),
        "category": cat,
        "requester": req,
        "active_technicians": active_techs,
        "is_overdue": bool(
            due_at_local
            and due_at_local < now
            and ticket.status in ('PENDING', 'ASSIGNED', 'IN_PROGRESS')
        ),
        "sla_alert_sent_at": _dt(ticket.sla_alert_sent_at),
    }


def serialize_ticket_detail(ticket: MaintTicket) -> dict:
    """Datos completos para la vista de detalle, incluyendo relaciones."""
    data = serialize_ticket_summary(ticket)

    try:
        resolved_by = {"id": ticket.resolved_by.id, "name": ticket.resolved_by.full_name}
    except Exception:
        resolved_by = None

    try:
        created_by = {"id": ticket.created_by_user.id, "name": ticket.created_by_user.full_name}
    except Exception:
        created_by = None

    try:
        canceled_by = {"id": ticket.canceled_by_user.id, "name": ticket.canceled_by_user.full_name}
    except Exception:
        canceled_by = None

    try:
        dept = ticket.requester_department.name if ticket.requester_department else None
    except Exception:
        dept = None

    # Puesto/cargo principal del solicitante (puede no existir)
    requester_position = None
    try:
        from itcj2.core.models.position import UserPosition, Position
        up = (
            ticket.requester
            and (
                ticket.requester.__dict__.get("_sa_instance_state")
                and None
            )
        )
        # Query directo (no asumir relación cargada)
        from sqlalchemy.orm import object_session
        sess = object_session(ticket)
        if sess and ticket.requester_id:
            row = (
                sess.query(Position.title)
                .join(UserPosition, UserPosition.position_id == Position.id)
                .filter(
                    UserPosition.user_id == ticket.requester_id,
                    UserPosition.is_active == True,
                )
                .order_by(UserPosition.start_date.desc())
                .first()
            )
            if row:
                requester_position = row[0]
    except Exception:
        requester_position = None

    try:
        technicians = [
            {
                "id": t.id,
                "user_id": t.user_id,
                "user_name": t.user.full_name if t.user else str(t.user_id),
                "assigned_at": _dt(t.assigned_at),
                "unassigned_at": _dt(t.unassigned_at),
                "notes": t.notes,
                "is_active": t.unassigned_at is None,
            }
            for t in ticket.technicians
        ]
    except Exception:
        technicians = []

    def _att_brief(att):
        return {
            "id": att.id,
            "original_filename": att.original_filename,
            "mime_type": att.mime_type,
            "file_size": att.file_size,
            "uploaded_at": _dt(att.uploaded_at),
            "is_purged": bool(att.is_purged),
            "purged_at": _dt(att.purged_at),
        }

    try:
        comments = [
            {
                "id": c.id,
                "content": c.content,
                "is_internal": c.is_internal,
                "created_at": _dt(c.created_at),
                "author": {
                    "id": c.author_id,
                    "name": c.author.full_name if c.author else str(c.author_id),
                },
                "attachments": [_att_brief(a) for a in (c.attachments or [])],
            }
            for c in sorted(ticket.comments, key=lambda x: x.created_at or 0)
        ]
    except Exception:
        comments = []

    try:
        ticket_attachments = [_att_brief(a) for a in (ticket.attachments or []) if a.attachment_type == 'ticket']
        resolution_attachments = [_att_brief(a) for a in (ticket.attachments or []) if a.attachment_type == 'resolution']
    except Exception:
        ticket_attachments = []
        resolution_attachments = []

    try:
        status_logs = [
            {
                "id": sl.id,
                "from_status": sl.from_status,
                "to_status": sl.to_status,
                "notes": sl.notes,
                "created_at": _dt(sl.created_at),
                "changed_by": {
                    "id": sl.changed_by_id,
                    "name": sl.changed_by.full_name if sl.changed_by else str(sl.changed_by_id),
                },
            }
            for sl in sorted(ticket.status_logs, key=lambda x: x.created_at or 0)
        ]
    except Exception:
        status_logs = []

    data.update({
        "description": ticket.description,
        "custom_fields": ticket.custom_fields or {},
        "requester_department": dept,
        "requester_position": requester_position,
        "maintenance_type": ticket.maintenance_type,
        "service_origin": ticket.service_origin,
        "resolution_notes": ticket.resolution_notes,
        "time_invested_minutes": ticket.time_invested_minutes,
        "observations": ticket.observations,
        "resolved_at": _dt(ticket.resolved_at),
        "resolved_by": resolved_by,
        "rating_attention": ticket.rating_attention,
        "rating_speed": ticket.rating_speed,
        "rating_efficiency": ticket.rating_efficiency,
        "rating_comment": ticket.rating_comment,
        "rated_at": _dt(ticket.rated_at),
        "closed_at": _dt(ticket.closed_at),
        "canceled_at": _dt(ticket.canceled_at),
        "cancel_reason": ticket.cancel_reason,
        "canceled_by": canceled_by,
        "created_by": created_by,
        "can_be_rated": ticket.can_be_rated,
        "is_open": ticket.is_open,
        "is_resolved": ticket.is_resolved,
        "technicians": technicians,
        "comments": comments,
        "status_logs": status_logs,
        "ticket_attachments": ticket_attachments,
        "resolution_attachments": resolution_attachments,
        # sla_alert_sent_at ya viene desde serialize_ticket_summary;
        # lo repetimos aquí explícitamente para la vista de detalle.
        "sla_alert_sent_at": _dt(ticket.sla_alert_sent_at),
    })
    return data
