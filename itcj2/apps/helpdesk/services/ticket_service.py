import logging
import os

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from werkzeug.utils import secure_filename
from PIL import Image

from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.apps.helpdesk.models.category import Category
from itcj2.apps.helpdesk.models.comment import Comment
from itcj2.apps.helpdesk.models.status_log import StatusLog
from itcj2.apps.helpdesk.utils.ticket_number_generator import generate_ticket_number
from itcj2.apps.helpdesk.utils.timezone_utils import now_local
from itcj2.apps.helpdesk.utils.custom_fields_validator import CustomFieldsValidator
from itcj2.apps.helpdesk.services.custom_fields_file_service import CustomFieldsFileService
from itcj2.core.models.user import User
from itcj2.core.models.department import Department
from itcj2.models.base import paginate

logger = logging.getLogger(__name__)


# ==================== GUARDAR FOTO DEL TICKET ====================

def _save_ticket_photo(db: Session, ticket_id, photo_file, uploader_id: int = None):
    """
    Guarda la foto de un ticket.
    """
    from itcj2.apps.helpdesk.models.attachment import Attachment
    from itcj2.config import get_settings

    s = get_settings()
    upload_path = s.HELPDESK_UPLOAD_PATH
    max_size = s.HELPDESK_MAX_FILE_SIZE
    allowed_extensions = set(s.HELPDESK_ALLOWED_EXTENSIONS.split(','))

    os.makedirs(upload_path, exist_ok=True)

    original_filename = secure_filename(photo_file.filename)
    if '.' not in original_filename:
        raise ValueError('Archivo sin extensión')

    file_ext = original_filename.rsplit('.', 1)[1].lower()
    if file_ext not in allowed_extensions:
        raise ValueError(f'Solo se permiten: {", ".join(allowed_extensions)}')

    raw = photo_file.file
    raw.seek(0, 2)
    file_size = raw.tell()
    raw.seek(0)

    if file_size > max_size:
        raise ValueError(f'El archivo no debe exceder {max_size // (1024*1024)}MB')

    filename = f"{ticket_id}.jpg"
    filepath = os.path.join(upload_path, filename)

    try:
        img = Image.open(raw)

        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode in ('RGBA', 'LA'):
                background.paste(img, mask=img.split()[-1])
            img = background

        max_size_dims = (1920, 1080)
        if img.width > max_size_dims[0] or img.height > max_size_dims[1]:
            img.thumbnail(max_size_dims, Image.Resampling.LANCZOS)

        img.save(filepath, format='JPEG', quality=85, optimize=True)

        final_size = os.path.getsize(filepath)

        logger.info(f"Foto guardada: {filepath} ({final_size} bytes)")

        attachment = Attachment(
            ticket_id=ticket_id,
            uploaded_by_id=uploader_id,
            filename=filename,
            original_filename=original_filename,
            filepath=filepath,
            mime_type='image/jpeg',
            file_size=final_size
        )

        db.add(attachment)

    except Exception as e:
        logger.error(f"Error al procesar imagen: {e}")
        if os.path.exists(filepath):
            os.remove(filepath)
        raise


# ==================== CREAR TICKET ====================
def create_ticket(
    db: Session,
    requester_id: int,
    area: str,
    category_id: int,
    title: str,
    description: str,
    priority: str = 'MEDIA',
    location: str = None,
    office_folio: str = None,
    inventory_item_ids: list = None,
    photo_file=None,
    custom_fields: dict = None,
    custom_field_files: dict = None,
    created_by_id: int = None
) -> Ticket:
    """
    Crea un nuevo ticket.
    """
    requester = db.get(User, requester_id)
    if not requester:
        raise HTTPException(status_code=404, detail='Usuario no encontrado')

    category = db.get(Category, category_id)
    if not category or not category.is_active:
        raise HTTPException(status_code=400, detail='Categoría inválida o inactiva')

    if category.area != area:
        raise HTTPException(status_code=400, detail=f'La categoría no corresponde al área {area}')

    if custom_fields or custom_field_files:
        if category.field_template and category.field_template.get('enabled'):
            is_valid, errors = CustomFieldsValidator.validate(
                category.field_template,
                custom_fields or {},
                custom_field_files or {}
            )

            if not is_valid:
                raise HTTPException(status_code=400, detail=f"Campos personalizados inválidos: {'; '.join(errors)}")

    if area not in ['DESARROLLO', 'SOPORTE']:
        raise HTTPException(status_code=400, detail='Área debe ser DESARROLLO o SOPORTE')

    if priority not in ['BAJA', 'MEDIA', 'ALTA', 'URGENTE']:
        raise HTTPException(status_code=400, detail='Prioridad inválida')

    department_id = None
    try:
        from itcj2.core.models.position import UserPosition
        user_position = db.query(UserPosition).filter_by(
            user_id=requester_id,
            is_active=True
        ).first()

        if user_position and user_position.position:
            department_id = user_position.position.department_id
    except Exception as e:
        logger.warning(f"No se pudo obtener departamento del usuario {requester_id}: {e}")

    ticket_number = generate_ticket_number(db)

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
        custom_fields=custom_fields or {},
        status='PENDING',
        created_by_id=created_by_id or requester_id,
        updated_by_id=created_by_id or requester_id
    )

    db.add(ticket)
    db.flush()

    if inventory_item_ids:
        try:
            from itcj2.apps.helpdesk.services.ticket_inventory_service import TicketInventoryService
            TicketInventoryService.add_items_to_ticket(db, ticket.id, inventory_item_ids)
            logger.warning(f"Ticket {ticket.ticket_number}: {len(inventory_item_ids)} equipos asociados")
        except Exception as e:
            logger.warning(f"Error al asociar equipos al ticket {ticket.id}: {e}")
            db.rollback()
            raise

    if custom_field_files and category.field_template:
        fields_config = category.field_template.get('fields', [])
        file_fields = {f['key']: f for f in fields_config if f['type'] == 'file'}

        for field_key, file in custom_field_files.items():
            if field_key in file_fields:
                try:
                    file_path = CustomFieldsFileService.save_custom_field_file(
                        ticket.id,
                        field_key,
                        file,
                        file_fields[field_key]
                    )
                    if ticket.custom_fields is None:
                        ticket.custom_fields = {}
                    ticket.custom_fields[field_key] = file_path

                    flag_modified(ticket, 'custom_fields')

                    logger.info(f"Archivo de campo personalizado '{field_key}' guardado para ticket {ticket.id}: {file_path}")
                except Exception as e:
                    logger.error(f"Error al guardar archivo de campo personalizado '{field_key}' para ticket {ticket.id}: {e}")
                    db.rollback()
                    raise

    if photo_file:
        try:
            _save_ticket_photo(db, ticket.id, photo_file, uploader_id=requester_id)
        except Exception as e:
            logger.error(f"Error al guardar foto del ticket {ticket.id}: {e}")

    status_log = StatusLog(
        ticket=ticket,
        from_status=None,
        to_status='PENDING',
        changed_by_id=requester_id,
        notes='Ticket creado'
    )
    db.add(status_log)

    try:
        db.commit()
        logger.info(f"Ticket {ticket.ticket_number} creado por usuario {requester_id}")
        return ticket
    except Exception as e:
        db.rollback()
        logger.error(f"Error al crear ticket: {e}")
        raise HTTPException(status_code=500, detail='Error al crear ticket')


# ==================== OBTENER TICKET ====================
def get_ticket_by_id(db: Session, ticket_id: int, user_id: int = None, check_permissions: bool = True) -> Ticket:
    """
    Obtiene un ticket por ID con validación de permisos.
    """
    ticket = db.get(Ticket, ticket_id)

    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    if check_permissions and user_id:
        if not can_user_view_ticket(db, ticket, user_id):
            raise HTTPException(status_code=403, detail='No tienes permiso para ver este ticket')

    return ticket


# ==================== LISTAR TICKETS ====================
def list_tickets(
    db: Session,
    user_id: int,
    user_roles: list,
    status=None,
    area: str = None,
    priority: str = None,
    assigned_to_me: bool = False,
    assigned_to_team: str = None,
    created_by_me: bool = False,
    department_id: int = None,
    search: str = None,
    page: int = 1,
    per_page: int = 20,
    include_metrics: bool = False
) -> dict:
    """
    Lista tickets según filtros y permisos del usuario.
    """
    from itcj2.core.services.authz_service import _get_users_with_position

    query = db.query(Ticket)

    secretary_comp_center = _get_users_with_position(db, ['secretary_comp_center'])

    if 'admin' in user_roles or user_id in secretary_comp_center:
        pass
    elif 'tech_desarrollo' in user_roles or 'tech_soporte' in user_roles:
        pass
    elif 'department_head' in user_roles:
        from itcj2.core.models.position import UserPosition
        user_position = db.query(UserPosition).filter_by(
            user_id=user_id,
            is_active=True
        ).first()

        if user_position and user_position.position:
            query = query.filter(Ticket.requester_department_id == user_position.position.department_id)
        else:
            query = query.filter(Ticket.id == -1)
    else:
        query = query.filter(Ticket.requester_id == user_id)

    if status:
        if isinstance(status, list):
            if len(status) == 1:
                query = query.filter(Ticket.status == status[0])
            else:
                query = query.filter(Ticket.status.in_(status))
        else:
            query = query.filter(Ticket.status == status)

    if area:
        query = query.filter(Ticket.area == area)

    if priority:
        query = query.filter(Ticket.priority == priority)

    if assigned_to_me:
        query = query.filter(Ticket.assigned_to_user_id == user_id)

    if assigned_to_team:
        query = query.filter(
            Ticket.assigned_to_team == assigned_to_team,
            Ticket.assigned_to_user_id == None
        )

    if created_by_me:
        query = query.filter(Ticket.requester_id == user_id)

    if department_id:
        query = query.filter(Ticket.requester_department_id == department_id)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Ticket.title.ilike(search_term),
                Ticket.ticket_number.ilike(search_term),
                Ticket.description.ilike(search_term)
            )
        )

    query = query.order_by(Ticket.created_at.desc())

    pagination = paginate(query, page=page, per_page=per_page)

    return {
        'tickets': [t.to_dict(include_relations=True, include_metrics=include_metrics) for t in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page,
        'per_page': per_page,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev
    }


# ==================== CAMBIAR ESTADO ====================
def change_status(
    db: Session,
    ticket_id: int,
    new_status: str,
    changed_by_id: int,
    notes: str = None
) -> Ticket:
    """
    Cambia el estado de un ticket y registra en el log.
    """
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    valid_statuses = ['PENDING', 'ASSIGNED', 'IN_PROGRESS', 'RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED', 'CANCELED']
    if new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail='Estado inválido')

    old_status = ticket.status

    if not _is_valid_status_transition(old_status, new_status):
        raise HTTPException(status_code=400, detail=f'Transición inválida de {old_status} a {new_status}')

    ticket.status = new_status
    ticket.updated_at = now_local()
    ticket.updated_by_id = changed_by_id

    if new_status == 'CLOSED':
        ticket.closed_at = now_local()

    status_log = StatusLog(
        ticket_id=ticket_id,
        from_status=old_status,
        to_status=new_status,
        changed_by_id=changed_by_id,
        notes=notes
    )
    db.add(status_log)

    try:
        db.commit()
        logger.info(f"Ticket {ticket.ticket_number} cambió de {old_status} a {new_status}")
        return ticket
    except Exception as e:
        db.rollback()
        logger.error(f"Error al cambiar estado del ticket: {e}")
        raise HTTPException(status_code=500, detail='Error al cambiar estado')


# ==================== RESOLVER TICKET ====================
def resolve_ticket(
    db: Session,
    ticket_id: int,
    resolved_by_id: int,
    success: bool,
    resolution_notes: str,
    time_invested_minutes: int,
    maintenance_type: str,
    service_origin: str,
    observations: str = None
) -> Ticket:
    """
    Marca un ticket como resuelto.
    """
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    if ticket.status not in ['ASSIGNED', 'IN_PROGRESS']:
        raise HTTPException(status_code=400, detail='El ticket no puede ser resuelto en su estado actual')

    if not resolution_notes or len(resolution_notes.strip()) < 10:
        raise HTTPException(status_code=400, detail='Las notas de resolución deben tener al menos 10 caracteres')

    if time_invested_minutes is None or time_invested_minutes <= 0:
        raise HTTPException(status_code=400, detail='El tiempo invertido es requerido y debe ser mayor a 0')

    if ticket.area == 'SOPORTE':
        if not maintenance_type or maintenance_type not in ['PREVENTIVO', 'CORRECTIVO']:
            raise HTTPException(status_code=400, detail='El tipo de mantenimiento es requerido (PREVENTIVO o CORRECTIVO)')
        if not service_origin or service_origin not in ['INTERNO', 'EXTERNO']:
            raise HTTPException(status_code=400, detail='El origen del servicio es requerido (INTERNO o EXTERNO)')
    else:
        if maintenance_type and maintenance_type not in ['PREVENTIVO', 'CORRECTIVO']:
            maintenance_type = None
        if service_origin and service_origin not in ['INTERNO', 'EXTERNO']:
            service_origin = None

    new_status = 'RESOLVED_SUCCESS' if success else 'RESOLVED_FAILED'
    ticket.status = new_status
    ticket.resolution_notes = resolution_notes
    ticket.resolved_at = now_local()
    ticket.resolved_by_id = resolved_by_id
    ticket.updated_at = now_local()
    ticket.updated_by_id = resolved_by_id
    ticket.time_invested_minutes = time_invested_minutes
    ticket.maintenance_type = maintenance_type
    ticket.service_origin = service_origin
    ticket.observations = observations.strip() if observations else None

    status_log = StatusLog(
        ticket_id=ticket_id,
        from_status=ticket.status,
        to_status=new_status,
        changed_by_id=resolved_by_id,
        notes=f'Ticket resuelto: {resolution_notes[:100]}'
    )
    db.add(status_log)

    # Los adjuntos se marcan para borrado solo cuando el ticket pasa a CLOSED
    # (cuando el solicitante lo evalúa), no en la resolución.
    # Eso lo maneja set_auto_delete_on_closed_tickets() en la tarea periódica.

    try:
        db.commit()
        logger.info(f"Ticket {ticket.ticket_number} resuelto por usuario {resolved_by_id}")
        return ticket
    except Exception as e:
        db.rollback()
        logger.error(f"Error al resolver ticket: {e}")
        raise HTTPException(status_code=500, detail='Error al resolver ticket')


# ==================== CALIFICAR TICKET ====================
def rate_ticket(
    db: Session,
    ticket_id: int,
    requester_id: int,
    rating_attention: int,
    rating_speed: int,
    rating_efficiency: bool,
    comment: str = None
) -> Ticket:
    """
    Usuario califica el servicio del ticket mediante encuesta.
    """
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    if ticket.requester_id != requester_id:
        raise HTTPException(status_code=403, detail='Solo el solicitante puede calificar')

    if ticket.status not in ['RESOLVED_SUCCESS', 'RESOLVED_FAILED']:
        raise HTTPException(status_code=400, detail='Solo se pueden calificar tickets resueltos')

    if ticket.rating_attention is not None:
        raise HTTPException(status_code=400, detail='Este ticket ya fue calificado')

    if not isinstance(rating_attention, int) or rating_attention < 1 or rating_attention > 5:
        raise HTTPException(status_code=400, detail='La calificación de atención debe ser entre 1 y 5')

    if not isinstance(rating_speed, int) or rating_speed < 1 or rating_speed > 5:
        raise HTTPException(status_code=400, detail='La calificación de rapidez debe ser entre 1 y 5')

    if not isinstance(rating_efficiency, bool):
        raise HTTPException(status_code=400, detail='La eficiencia debe ser un valor booleano')

    previous_status = ticket.status

    ticket.rating_attention = rating_attention
    ticket.rating_speed = rating_speed
    ticket.rating_efficiency = rating_efficiency
    ticket.rating_comment = comment
    ticket.rated_at = now_local()
    ticket.status = 'CLOSED'
    ticket.closed_at = now_local()
    ticket.updated_at = now_local()
    ticket.updated_by_id = requester_id

    status_log = StatusLog(
        ticket_id=ticket_id,
        from_status=previous_status,
        to_status='CLOSED',
        changed_by_id=requester_id,
        notes=f'Ticket calificado - Atención: {rating_attention}/5, Rapidez: {rating_speed}/5, Eficiencia: {"Sí" if rating_efficiency else "No"}'
    )
    db.add(status_log)

    try:
        db.commit()
        logger.info(f"Ticket {ticket.ticket_number} calificado - Atención: {rating_attention}/5, Rapidez: {rating_speed}/5")
        return ticket
    except Exception as e:
        db.rollback()
        logger.error(f"Error al calificar ticket: {e}")
        raise HTTPException(status_code=500, detail='Error al calificar ticket')


# ==================== CANCELAR TICKET ====================
def cancel_ticket(db: Session, ticket_id: int, user_id: int, reason: str = None) -> Ticket:
    """
    Usuario cancela su ticket.
    """
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    if ticket.requester_id != user_id:
        raise HTTPException(status_code=403, detail='Solo el solicitante puede cancelar')

    if ticket.status in ['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED', 'CANCELED']:
        raise HTTPException(status_code=400, detail='No se puede cancelar un ticket ya resuelto o cerrado')

    old_status = ticket.status
    ticket.status = 'CANCELED'
    ticket.closed_at = now_local()
    ticket.updated_at = now_local()
    ticket.updated_by_id = user_id

    status_log = StatusLog(
        ticket_id=ticket_id,
        from_status=old_status,
        to_status='CANCELED',
        changed_by_id=user_id,
        notes=f'Ticket cancelado: {reason}' if reason else 'Ticket cancelado'
    )
    db.add(status_log)

    try:
        db.commit()
        logger.info(f"Ticket {ticket.ticket_number} cancelado por usuario {user_id}")
        return ticket
    except Exception as e:
        db.rollback()
        logger.error(f"Error al cancelar ticket: {e}")
        raise HTTPException(status_code=500, detail='Error al cancelar ticket')


# ==================== AGREGAR COMENTARIO ====================
def add_comment(
    db: Session,
    ticket_id: int,
    author_id: int,
    content: str,
    is_internal: bool = False
) -> Comment:
    """
    Agrega un comentario a un ticket.
    """
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    if not content or len(content.strip()) < 3:
        raise HTTPException(status_code=400, detail='El comentario debe tener al menos 3 caracteres')

    comment = Comment(
        ticket_id=ticket_id,
        author_id=author_id,
        content=content.strip(),
        is_internal=is_internal
    )

    db.add(comment)
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


# ==================== FUNCIONES AUXILIARES ====================
def can_user_view_ticket(db: Session, ticket: Ticket, user_id: int) -> bool:
    """
    Verifica si un usuario puede ver un ticket específico.
    """
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position

    user_roles = user_roles_in_app(db, user_id, 'helpdesk')
    secretary_comp_center = _get_users_with_position(db, ['secretary_comp_center'])

    if 'admin' in user_roles or user_id in secretary_comp_center:
        return True

    if 'tech_desarrollo' in user_roles or 'tech_soporte' in user_roles:
        return True

    if ticket.requester_id == user_id:
        return True

    if ticket.assigned_to_user_id == user_id:
        return True

    if 'department_head' in user_roles:
        from itcj2.core.models.position import UserPosition
        user_position = db.query(UserPosition).filter_by(
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
    """
    valid_transitions = {
        'PENDING': ['ASSIGNED', 'CANCELED'],
        'ASSIGNED': ['IN_PROGRESS', 'PENDING', 'CANCELED'],
        'IN_PROGRESS': ['ASSIGNED', 'RESOLVED_SUCCESS', 'RESOLVED_FAILED'],
        'RESOLVED_SUCCESS': ['CLOSED'],
        'RESOLVED_FAILED': ['CLOSED', 'ASSIGNED'],
        'CLOSED': [],
        'CANCELED': []
    }

    return to_status in valid_transitions.get(from_status, [])


# ==================== EDITAR TICKET PENDIENTE ====================
def update_pending_ticket(
    db: Session,
    ticket_id: int,
    updated_by_id: int,
    area: str = None,
    category_id: int = None,
    priority: str = None,
    title: str = None,
    description: str = None,
    location: str = None
) -> Ticket:
    """
    Edita campos de un ticket en estado PENDING.
    """
    from itcj2.apps.helpdesk.models.ticket_edit_log import TicketEditLog

    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    if ticket.status != 'PENDING':
        raise HTTPException(status_code=400, detail='Solo se pueden editar tickets en estado PENDING')

    changes = []

    if area and area != ticket.area:
        if area not in ['DESARROLLO', 'SOPORTE']:
            raise HTTPException(status_code=400, detail='Area debe ser DESARROLLO o SOPORTE')

        if not category_id:
            raise HTTPException(status_code=400, detail='Al cambiar de area debe seleccionar una nueva categoria')

        changes.append({
            'field': 'area',
            'old': ticket.area,
            'new': area
        })
        ticket.area = area

    if category_id and category_id != ticket.category_id:
        category = db.get(Category, category_id)
        if not category or not category.is_active:
            raise HTTPException(status_code=400, detail='Categoria invalida o inactiva')

        target_area = area or ticket.area
        if category.area != target_area:
            raise HTTPException(status_code=400, detail=f'La categoria no corresponde al area {target_area}')

        old_category = db.get(Category, ticket.category_id)
        old_category_name = old_category.name if old_category else str(ticket.category_id)

        changes.append({
            'field': 'category_id',
            'old': old_category_name,
            'new': category.name
        })

        if ticket.custom_fields and len(ticket.custom_fields) > 0:
            changes.append({
                'field': 'custom_fields',
                'old': str(ticket.custom_fields),
                'new': '{}'
            })
            ticket.custom_fields = {}
            flag_modified(ticket, 'custom_fields')

        ticket.category_id = category_id

    if priority and priority != ticket.priority:
        if priority not in ['BAJA', 'MEDIA', 'ALTA', 'URGENTE']:
            raise HTTPException(status_code=400, detail='Prioridad invalida')

        changes.append({
            'field': 'priority',
            'old': ticket.priority,
            'new': priority
        })
        ticket.priority = priority

    if title is not None and title.strip() != ticket.title:
        if len(title.strip()) < 5:
            raise HTTPException(status_code=400, detail='El titulo debe tener al menos 5 caracteres')

        changes.append({
            'field': 'title',
            'old': ticket.title,
            'new': title.strip()
        })
        ticket.title = title.strip()

    if description is not None and description.strip() != ticket.description:
        if len(description.strip()) < 20:
            raise HTTPException(status_code=400, detail='La descripcion debe tener al menos 20 caracteres')

        changes.append({
            'field': 'description',
            'old': ticket.description,
            'new': description.strip()
        })
        ticket.description = description.strip()

    if location is not None and location != ticket.location:
        changes.append({
            'field': 'location',
            'old': ticket.location or '',
            'new': location or ''
        })
        ticket.location = location if location else None

    if not changes:
        return ticket

    ticket.updated_at = now_local()
    ticket.updated_by_id = updated_by_id

    for change in changes:
        edit_log = TicketEditLog(
            ticket_id=ticket_id,
            field_name=change['field'],
            old_value=change['old'],
            new_value=change['new'],
            changed_by_id=updated_by_id
        )
        db.add(edit_log)

    try:
        db.commit()
        logger.info(f"Ticket {ticket.ticket_number} editado: {len(changes)} campo(s) modificado(s) por usuario {updated_by_id}")
        return ticket
    except Exception as e:
        db.rollback()
        logger.error(f"Error al editar ticket: {e}")
        raise HTTPException(status_code=500, detail='Error al editar ticket')
