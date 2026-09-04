import logging
import os

from fastapi import HTTPException
from sqlalchemy import and_, case, or_
from sqlalchemy.orm import Session, aliased
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

def _save_ticket_photo(db: Session, ticket_id, photo_file, uploader_id: int = None, area: str = None):
    """
    Guarda la foto/archivo inicial de un ticket.
    En área DESARROLLO se permiten también documentos (PDF, Word, Excel, CSV).
    En área SOPORTE solo se permiten imágenes.
    """
    from itcj2.apps.helpdesk.models.attachment import Attachment
    from itcj2.config import get_settings

    s = get_settings()
    upload_path = s.HELPDESK_UPLOAD_PATH
    img_extensions = set(s.HELPDESK_ALLOWED_EXTENSIONS.split(','))
    doc_extensions = set(s.HELPDESK_ALLOWED_DOC_EXTENSIONS.split(','))

    # DESARROLLO: imágenes + documentos (hasta 25MB)
    # SOPORTE y default: solo imágenes (hasta 3MB)
    if area == "DESARROLLO":
        allowed_extensions = img_extensions | doc_extensions
        max_size = s.HELPDESK_MAX_DOCUMENT_SIZE
    else:
        allowed_extensions = img_extensions
        max_size = s.HELPDESK_MAX_FILE_SIZE

    os.makedirs(upload_path, exist_ok=True)

    original_filename = secure_filename(photo_file.filename)
    if '.' not in original_filename:
        raise ValueError('Archivo sin extensión')

    file_ext = original_filename.rsplit('.', 1)[1].lower()
    if file_ext not in allowed_extensions:
        raise ValueError(f'Solo se permiten: {", ".join(sorted(allowed_extensions))}')

    raw = photo_file.file
    raw.seek(0, 2)
    file_size = raw.tell()
    raw.seek(0)

    if file_size > max_size:
        raise ValueError(f'El archivo no debe exceder {max_size // (1024*1024)}MB')

    is_image = file_ext in img_extensions

    if is_image:
        filename = f"{ticket_id}.jpg"
        mime_type = 'image/jpeg'
    else:
        filename = f"{ticket_id}_doc.{file_ext}"
        _doc_mime_map = {
            'pdf': 'application/pdf',
            'doc': 'application/msword',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'xls': 'application/vnd.ms-excel',
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'csv': 'text/csv',
        }
        mime_type = _doc_mime_map.get(file_ext, 'application/octet-stream')

    filepath = os.path.join(upload_path, filename)

    try:
        if is_image:
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
        else:
            # gzip transparente: se guarda comprimido solo si reduce tamaño
            # (PDF/Office ya vienen comprimidos). Se descomprime al descargar.
            import gzip as _gzip
            raw.seek(0)
            raw_bytes = raw.read()
            gz_bytes = _gzip.compress(raw_bytes, compresslevel=6)
            if len(gz_bytes) < len(raw_bytes):
                filename += '.gz'
                filepath += '.gz'
                with open(filepath, 'wb') as f:
                    f.write(gz_bytes)
                logger.info(f"Documento adjunto comprimido gzip: {len(raw_bytes)} -> {len(gz_bytes)} bytes ({filepath})")
            else:
                with open(filepath, 'wb') as f:
                    f.write(raw_bytes)
                logger.info(f"Documento adjunto guardado: {filepath} ({len(raw_bytes)} bytes)")
            final_size = len(raw_bytes)

        attachment = Attachment(
            ticket_id=ticket_id,
            uploaded_by_id=uploader_id,
            filename=filename,
            original_filename=original_filename,
            filepath=filepath,
            mime_type=mime_type,
            file_size=final_size
        )

        db.add(attachment)

    except Exception as e:
        logger.error(f"Error al procesar archivo del ticket: {e}")
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

    from itcj2.apps.helpdesk.utils.catalog_cache import get_area_codes
    valid_areas = get_area_codes(db, active_only=True)
    if area not in valid_areas:
        raise HTTPException(status_code=400, detail=f'Área inválida. Válidas: {sorted(valid_areas)}')

    from itcj2.apps.helpdesk.utils.catalog_cache import get_priority_codes
    valid_codes = get_priority_codes(db, active_only=True)
    if priority not in valid_codes:
        raise HTTPException(status_code=400, detail=f'Prioridad inválida. Válidas: {sorted(valid_codes)}')

    # Este campo se SELLA aquí y nadie lo recalcula después: de él depende todo el
    # scope departamental posterior del ticket. La consulta ad-hoc que había aquí
    # (is_active a secas + .first() sin orden) podía sellarlo con un puesto vencido
    # o, en usuarios multi-puesto, con uno arbitrario — y el ticket quedaba invisible
    # para el jefe correcto de forma permanente. Se usa el resolver canónico.
    department_id = None
    try:
        from itcj2.core.services.departments_service import primary_app_department
        # Por PROCEDENCIA: entre los puestos del solicitante, solo anclan los que
        # le dan acceso a helpdesk. Con el resolver agnóstico, alguien con un
        # puesto en un departamento ajeno a la app (y más antiguo) veía su ticket
        # sellado con ESE departamento.
        dept = primary_app_department(db, requester_id, "helpdesk")
        if dept:
            department_id = dept.id
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
            _save_ticket_photo(db, ticket.id, photo_file, uploader_id=requester_id, area=area)
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


# Órdenes soportados por el filtro `sort` de la lista de tickets. `recent` es el
# default histórico (created_at desc); `stale` = más tiempo sin actualizar
# (updated_at asc).
_SORT_CLAUSES = {
    'oldest': lambda: [Ticket.created_at.asc()],
    'priority': lambda: [
        case(
            (Ticket.priority == 'URGENTE', 1),
            (Ticket.priority == 'ALTA', 2),
            (Ticket.priority == 'MEDIA', 3),
            (Ticket.priority == 'BAJA', 4),
            else_=5,
        ),
        Ticket.created_at.desc(),
    ],
    'stale': lambda: [Ticket.updated_at.asc()],
}


# ==================== LISTAR TICKETS ====================
def department_scope_ids(db, user_id: int) -> set[int]:
    """Los departamentos cuyos tickets alcanza este usuario. Aditivo.

      * `read.department` -> sus departamentos por PROCEDENCIA (los de los puestos
        que le otorgan helpdesk), en plural.
      * `read.subtree`    -> además, sus sub-departamentos.

    Es el ÚNICO sitio donde se decide esto. Lo consumen la visibilidad de
    `list_tickets`, `can_user_view_ticket` y el filtro del dashboard de
    secretaría. Cuando el dashboard calculaba su propio conjunto por su cuenta
    —el subárbol del departamento agnóstico— filtraba por un conjunto distinto
    del que la visibilidad permitía: a una secretaría le sobraba anchura muerta,
    y a un jefe con `read.subtree` un filtro exacto le habría borrado sus
    sub-departamentos (medido: 486 tickets -> 20).
    """
    from itcj2.core.services.departments_service import app_departments
    from itcj2.core.services.scope_service import subtree_scope_for

    dept_ids: set[int] = set()
    if _tiene_scope_departamental(db, user_id):
        dept_ids |= {d.id for d in app_departments(db, user_id, "helpdesk")}
    dept_ids |= subtree_scope_for(db, user_id, "helpdesk",
                                  "helpdesk.tickets.api.read.subtree")
    return dept_ids


def _tiene_scope_departamental(db, user_id: int) -> bool:
    """¿Puede leer los tickets de SU departamento?

    Se pregunta por el PERMISO (`helpdesk.tickets.api.read.department`), no por
    el rol. Antes era `'department_head' in user_roles`, y ahí se caían las
    secretarías: tienen el permiso y nunca entraban a la rama, así que solo veían
    los tickets donde eran solicitantes o asignadas. No saltaba a la vista porque
    la secretaría levanta casi todos los tickets de su departamento — una veía 20
    de los 21 del suyo, y el que faltaba era el que había creado otra persona.

    Comprobado sobre la base antes de cambiarlo: 0 personas tienen el rol
    `department_head` sin este permiso, así que nadie pierde alcance; lo ganan
    las 28 secretarías a las que el DML ya se lo había concedido.
    """
    from itcj2.core.services.authz_service import effective_perm_set
    return "helpdesk.tickets.api.read.department" in effective_perm_set(db, user_id, "helpdesk")


def list_tickets(
    db: Session,
    user_id: int,
    user_roles: list,
    status=None,
    area: str = None,
    priority: str = None,
    assigned_to_me: bool = False,
    assigned_to_team: str = None,
    assigned_to_user_id: int = None,
    unassigned: bool = False,
    created_by_me: bool = False,
    department_id: int = None,
    department_ids: set = None,
    category_id: int = None,
    created_from=None,
    created_to=None,
    search: str = None,
    sort: str = 'recent',
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
    else:
        # Scope departamental/subárbol. El criterio vive en `department_scope_ids`,
        # que es también el que usa el dashboard de secretaría para su filtro.
        dept_ids = department_scope_ids(db, user_id)

        # La propiedad NUNCA se pierde: el scope departamental SUMA sobre "soy el
        # solicitante / me lo asignaron", no lo reemplaza. `requester_department_id`
        # es un snapshot al crear, así que quien cambia de departamento conserva
        # tickets propios sellados con el departamento anterior; en AND se le
        # borrarían de "Mis Tickets". Mismo conjunto que `can_user_view_ticket`
        # → lista y detalle no se desalinean.
        visibility = [
            Ticket.requester_id == user_id,
            Ticket.assigned_to_user_id == user_id,
        ]
        if dept_ids:
            visibility.append(Ticket.requester_department_id.in_(dept_ids))
        query = query.filter(or_(*visibility))

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

    # Filtro de técnico asignado (barra de filtros admin): id exacto, o "sin
    # asignar del todo" (ni usuario ni equipo) — distinto de `assigned_to_team`
    # arriba, que es "en cola de un equipo, sin técnico todavía".
    if assigned_to_user_id:
        query = query.filter(Ticket.assigned_to_user_id == assigned_to_user_id)

    if unassigned:
        query = query.filter(
            Ticket.assigned_to_user_id.is_(None),
            Ticket.assigned_to_team.is_(None),
        )

    if category_id:
        query = query.filter(Ticket.category_id == category_id)

    if created_by_me:
        query = query.filter(Ticket.requester_id == user_id)

    if department_ids is not None:
        # Conjunto explícito de departamentos (el caller ya resolvió el ámbito:
        # propio / subárbol / solo sub-departamentos). Vacío → 0 resultados.
        query = query.filter(Ticket.requester_department_id.in_(department_ids or {-1}))
    elif department_id:
        # Filtro por departamento = su SUBÁRBOL (depto + sub-departamentos), coherente
        # con el scope jerárquico. Un depto sin hijos = sólo él (comportamiento previo).
        from itcj2.core.services.hierarchy_service import descendant_department_ids
        query = query.filter(
            Ticket.requester_department_id.in_(descendant_department_ids(db, department_id, include_self=True))
        )

    if created_from:
        query = query.filter(Ticket.created_at >= created_from)

    if created_to:
        # Límite superior EXCLUSIVO al día siguiente: `created_to` es una fecha
        # (sin hora), así que un `<=` directo contra un datetime cortaría el
        # propio día seleccionado a la medianoche.
        from datetime import date as _date, datetime as _datetime, time as _time, timedelta as _timedelta
        _end = created_to
        if isinstance(_end, _date) and not isinstance(_end, _datetime):
            _end = _datetime.combine(_end, _time.min)
        query = query.filter(Ticket.created_at < _end + _timedelta(days=1))

    if search:
        # Cubre también nombre del solicitante y del asignado (el placeholder de
        # búsqueda de la barra de filtros ya lo prometía; antes solo tocaba
        # title/ticket_number/description). outerjoin porque `assigned_to` puede
        # ser NULL (ticket sin asignar todavía).
        Requester = aliased(User)
        Assignee = aliased(User)
        query = (
            query
            .outerjoin(Requester, Ticket.requester_id == Requester.id)
            .outerjoin(Assignee, Ticket.assigned_to_user_id == Assignee.id)
        )
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Ticket.title.ilike(search_term),
                Ticket.ticket_number.ilike(search_term),
                Ticket.description.ilike(search_term),
                Requester.full_name.ilike(search_term),
                Assignee.full_name.ilike(search_term),
            )
        )

    order_clauses = _SORT_CLAUSES.get(sort, lambda: [Ticket.created_at.desc()])()
    query = query.order_by(*order_clauses)

    pagination = paginate(query, page=page, per_page=per_page)

    return {
        'tickets': [t.to_dict(include_relations=True, include_metrics=include_metrics, db=db if include_metrics else None) for t in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page,
        'per_page': per_page,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev
    }


# Buckets de estatus para el resumen por divisiones (jefe/director).
_SUMMARY_ACTIVE = ('PENDING', 'ASSIGNED', 'IN_PROGRESS')
_SUMMARY_RESOLVED = ('RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED')


def _summary_visible_departments(db: Session, user_id: int, root_department_id: int):
    """Departamentos cuyos conteos puede ver ``user_id``. ``None`` = sin recorte.

    Mismo criterio que ``list_tickets``: acceso total para admin / secretaría de
    centro de cómputo / técnicos; para el resto, el subárbol autorizado más el
    departamento raíz que ya gestiona (ese siempre lo ve, con permiso o sin él).
    """
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj2.core.services.scope_service import subtree_scope_for

    roles = set(user_roles_in_app(db, user_id, 'helpdesk'))
    if roles & {'admin', 'tech_desarrollo', 'tech_soporte'}:
        return None
    if user_id in set(_get_users_with_position(db, ['secretary_comp_center'])):
        return None

    return subtree_scope_for(db, user_id, "helpdesk", "helpdesk.tickets.api.read.subtree") | {root_department_id}


def subtree_department_summary(db: Session, user_id: int, root_department_id: int) -> list[dict]:
    """Árbol de divisiones del subárbol de ``root_department_id`` con conteos de
    tickets por departamento (total / activos / resueltos) + rollup de subtree.

    Incluye las divisiones del subárbol que el usuario PUEDE VER (aunque tengan 0
    tickets) en orden jerárquico. Para el resumen del dashboard del jefe/director:
    el root ve el total de su área y puede desplegar las divisiones internas.

    El recorte por scope es obligatorio: este widget agrega conteos sin pasar por
    ``list_tickets``, así que sin él un jefe sin ``helpdesk.tickets.api.read.subtree``
    vería los totales de cada sub-departamento mientras su lista de tickets devuelve
    solo los de su propio departamento.
    """
    from sqlalchemy import func
    from itcj2.core.services.hierarchy_service import subtree_nodes, build_dept_forest

    nodes = subtree_nodes(db, root_department_id)
    if not nodes:
        return []

    visible = _summary_visible_departments(db, user_id, root_department_id)
    if visible is not None:
        nodes = [n for n in nodes if n["id"] in visible]
        if not nodes:
            return []

    dept_ids = [n["id"] for n in nodes]
    rows = (
        db.query(Ticket.requester_department_id, Ticket.status, func.count(Ticket.id))
        .filter(Ticket.requester_department_id.in_(dept_ids))
        .group_by(Ticket.requester_department_id, Ticket.status)
        .all()
    )

    counts: dict[int, dict] = {}
    for dept_id, status, n in rows:
        c = counts.setdefault(dept_id, {"total": 0, "active": 0, "resolved": 0})
        c["total"] += n
        if status in _SUMMARY_ACTIVE:
            c["active"] += n
        elif status in _SUMMARY_RESOLVED:
            c["resolved"] += n

    return build_dept_forest(nodes, counts)


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

    from itcj2.apps.helpdesk.utils.catalog_cache import get_status_codes, is_transition_allowed
    valid_statuses = get_status_codes(db, active_only=False)
    if new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail='Estado inválido')

    old_status = ticket.status

    if not _is_valid_status_transition(old_status, new_status, db):
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
def cancel_ticket(
    db: Session,
    ticket_id: int,
    user_id: int,
    reason: str = None,
    user_dept_code: str = None,
) -> Ticket:
    """
    Cancela un ticket.

    Puede cancelar:
    - El solicitante original del ticket.
    - Cualquier usuario cuyo departamento activo tenga code='comp_center',
      siempre que el ticket no esté en estado terminal.
    """
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail='Ticket no encontrado')

    is_comp_center = (user_dept_code == 'comp_center')
    is_requester = (ticket.requester_id == user_id)

    if not (is_comp_center or is_requester):
        raise HTTPException(
            status_code=403,
            detail='Solo el solicitante o Centro de Cómputo puede cancelar este ticket',
        )

    if ticket.status in ['RESOLVED_SUCCESS', 'RESOLVED_FAILED', 'CLOSED', 'CANCELED']:
        raise HTTPException(status_code=400, detail='No se puede cancelar un ticket ya resuelto o cerrado')

    old_status = ticket.status
    ticket.status = 'CANCELED'
    ticket.closed_at = now_local()
    ticket.updated_at = now_local()
    ticket.updated_by_id = user_id

    if is_comp_center and not is_requester:
        notes = f'Cancelado por Centro de Cómputo: {reason}' if reason else 'Cancelado por Centro de Cómputo'
    else:
        notes = f'Ticket cancelado: {reason}' if reason else 'Ticket cancelado'

    status_log = StatusLog(
        ticket_id=ticket_id,
        from_status=old_status,
        to_status='CANCELED',
        changed_by_id=user_id,
        notes=notes,
    )
    db.add(status_log)

    try:
        db.commit()
        logger.info(f"Ticket {ticket.ticket_number} cancelado por usuario {user_id} (comp_center={is_comp_center})")
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

    # Colaborador del ticket. `collaborator_service.get_tickets_where_user_collaborated`
    # ya se lo lista, así que sin esto lo veía en su lista y recibía 403 al abrirlo.
    # `getattr` porque varios tests construyen tickets ligeros sin `id`.
    _ticket_id = getattr(ticket, 'id', None)
    if _ticket_id is not None:
        from itcj2.apps.helpdesk.models.collaborator import TicketCollaborator
        is_collaborator = db.query(
            db.query(TicketCollaborator)
            .filter_by(ticket_id=_ticket_id, user_id=user_id)
            .exists()
        ).scalar()
        if is_collaborator:
            return True

    # Scope departamental/subárbol: el MISMO conjunto que `list_tickets`, por
    # construcción y no por disciplina — antes eran dos copias que había que
    # acordarse de mover juntas.
    dept_ids = department_scope_ids(db, user_id)

    if ticket.requester_department_id in dept_ids:
        return True

    return False


def _is_valid_status_transition(from_status: str, to_status: str, db: Session) -> bool:
    """
    Valida si una transición de estado es válida consultando el catálogo en BD.
    from == to siempre se acepta (no-op). Fallback defensivo al dict literal
    si el cache no está disponible (tests, boot sin BD).
    """
    if from_status == to_status:
        return True
    try:
        from itcj2.apps.helpdesk.utils.catalog_cache import is_transition_allowed
        return is_transition_allowed(db, from_status, to_status)
    except Exception:
        # fallback defensivo si la tabla aún no existe (migraciones pendientes)
        _fallback = {
            'PENDING': {'ASSIGNED', 'CANCELED'},
            'ASSIGNED': {'IN_PROGRESS', 'PENDING', 'CANCELED'},
            'IN_PROGRESS': {'ASSIGNED', 'RESOLVED_SUCCESS', 'RESOLVED_FAILED'},
            'RESOLVED_SUCCESS': {'CLOSED'},
            'RESOLVED_FAILED': {'CLOSED', 'ASSIGNED'},
            'CLOSED': set(),
            'CANCELED': set(),
        }
        return to_status in _fallback.get(from_status, set())


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
        from itcj2.apps.helpdesk.utils.catalog_cache import get_area_codes
        valid_areas = get_area_codes(db, active_only=True)
        if area not in valid_areas:
            raise HTTPException(status_code=400, detail=f'Área inválida. Válidas: {sorted(valid_areas)}')

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
        from itcj2.apps.helpdesk.utils.catalog_cache import get_priority_codes
        valid_codes = get_priority_codes(db, active_only=True)
        if priority not in valid_codes:
            raise HTTPException(status_code=400, detail=f'Prioridad inválida. Válidas: {sorted(valid_codes)}')

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
