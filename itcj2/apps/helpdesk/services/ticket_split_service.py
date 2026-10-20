"""
Servicio para partir un ticket de helpdesk en varios (feature "Partir ticket").

Llegan solicitudes que en realidad son varias ("cuentas de Moodle, correo y SII").
El ticket original queda como la parte 1 —se edita para acotarlo a una sola cosa y
conserva folio, adjuntos, equipos, historial y asignación— y se crean de 1 a
`MAX_TOTAL_PARTS - 1` tickets nuevos a nombre del mismo solicitante, que nacen
PENDING y sin asignar (pueden ser de otra área).

Es todo o nada: cualquier fallo hace rollback y borra los archivos que alcanzaron
a copiarse. Los adjuntos iniciales (`attachment_type='ticket'`) se copian
FÍSICAMENTE a cada parte: la limpieza automática borra el archivo de cada ticket
al cerrarse, así que una ruta compartida dejaría a la otra parte sin el suyo.

No notifica ni emite sockets: eso lo hace el endpoint después del commit.
"""
import copy
import logging
import os
import shutil
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from itcj2.apps.helpdesk.models.attachment import Attachment
from itcj2.apps.helpdesk.models.category import Category
from itcj2.apps.helpdesk.models.status_log import StatusLog
from itcj2.apps.helpdesk.models.ticket import Ticket
from itcj2.apps.helpdesk.models.ticket_edit_log import TicketEditLog
from itcj2.apps.helpdesk.utils.ticket_number_generator import generate_ticket_number
from itcj2.apps.helpdesk.utils.timezone_utils import now_local

logger = logging.getLogger(__name__)

# Los terminales (resueltos, cerrado, cancelado) no: ya no hay trabajo que repartir.
SPLITTABLE_STATUSES = ("PENDING", "ASSIGNED", "IN_PROGRESS")

# Tope de partes CONTANDO al original: freno a una creación masiva por error.
MAX_TOTAL_PARTS = 5

# Mismas reglas que el alta de tickets; el máximo es el de `Ticket.title` (String(200)).
_TITLE_MIN_LEN = 5
_TITLE_MAX_LEN = 200
_DESCRIPTION_MIN_LEN = 20


# ==================== PARTIR TICKET ====================
def split_ticket(
    db: Session,
    ticket_id: int,
    split_by_id: int,
    original: dict,
    parts: list[dict],
) -> tuple[Ticket, list[Ticket]]:
    """
    Parte el ticket `ticket_id` en `1 + len(parts)` tickets.

    `original` (lo que conserva el ticket original) y cada elemento de `parts`
    (un ticket nuevo por elemento) son dicts con `area`, `category_id`,
    `priority`, `title` y `description`.

    Devuelve `(ticket_original, partes_nuevas)` ya commiteados, las partes en el
    orden de `parts`. Errores (`HTTPException`): 404 si no existe; 400 por estado,
    número de partes o validación ("Parte K: ..." / "Ticket original: ..."); 500
    ante cualquier otro fallo. En todos los casos hace rollback y borra las copias
    de adjuntos que alcanzó a crear.
    """
    copied_paths: list[str] = []
    try:
        ticket = db.get(Ticket, ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail='Ticket no encontrado')

        if ticket.status not in SPLITTABLE_STATUSES:
            raise HTTPException(
                status_code=400,
                detail='Solo se pueden partir tickets pendientes, asignados o en proceso',
            )

        parts = list(parts or [])
        max_new_parts = MAX_TOTAL_PARTS - 1
        if not 1 <= len(parts) <= max_new_parts:
            raise HTTPException(
                status_code=400,
                detail=(
                    f'Se deben crear entre 1 y {max_new_parts} tickets nuevos '
                    f'(máximo {MAX_TOTAL_PARTS} partes en total)'
                ),
            )

        original = original or {}
        new_area = original.get('area')
        # El técnico asignado es del área del ticket: fuera de PENDING no se mueve.
        if ticket.status != 'PENDING' and new_area and new_area != ticket.area:
            raise HTTPException(
                status_code=400,
                detail='Ticket original: no se puede cambiar el área de un ticket asignado o en proceso',
            )

        # Todas las partes nuevas se validan ANTES de mutar nada. El original no
        # pasa por estas reglas: `apply_ticket_field_edits` valida solo lo que
        # cambia, y un ticket viejo con descripción corta no debe bloquear la división.
        new_parts = [_validate_part(db, part, number) for number, part in enumerate(parts, start=2)]

        # Foto del original ANTES de editarlo: cambiarle la categoría le vacía
        # `custom_fields`, y las partes que conservan la categoría previa los heredan.
        previous_category_id = ticket.category_id
        inheritable_fields = _inheritable_custom_fields(
            ticket.custom_fields, db.get(Category, previous_category_id)
        )
        ticket_attachments = (
            ticket.attachments
            .filter_by(attachment_type='ticket')
            .order_by(Attachment.id)
            .all()
        )
        created_at = ticket.created_at

        _edit_original(db, ticket, split_by_id, original)

        new_tickets = []
        for data in new_parts:
            part = Ticket(
                ticket_number=generate_ticket_number(db),
                requester_id=ticket.requester_id,
                # Sellado del original, no recalculado: es snapshot y recalcularlo
                # podría sacar una parte del alcance del jefe que ve el original.
                requester_department_id=ticket.requester_department_id,
                area=data['area'],
                category_id=data['category_id'],
                priority=data['priority'],
                title=data['title'],
                description=data['description'],
                location=ticket.location,
                office_document_folio=ticket.office_document_folio,
                custom_fields=(
                    copy.deepcopy(inheritable_fields)
                    if data['category_id'] == previous_category_id else {}
                ),
                status='PENDING',
                # El SLA y el tiempo de espera cuentan desde la solicitud real; el
                # momento del corte queda en el StatusLog de la parte.
                created_at=created_at,
                created_by_id=split_by_id,
                updated_by_id=split_by_id,
                split_from_ticket_id=ticket.id,
            )
            db.add(part)
            # El siguiente `generate_ticket_number` debe ver este folio (la sesión
            # de la app corre con autoflush=False).
            db.flush()

            db.add(StatusLog(
                ticket=part,
                from_status=None,
                to_status='PENDING',
                changed_by_id=split_by_id,
                notes=f'Ticket creado al partir {ticket.ticket_number}',
            ))

            for attachment in ticket_attachments:
                _copy_ticket_attachment(db, attachment, part.id, copied_paths)

            new_tickets.append(part)

        part_numbers = ', '.join(p.ticket_number for p in new_tickets)
        db.add(TicketEditLog(
            ticket_id=ticket.id,
            field_name='split',
            old_value=None,
            new_value=part_numbers,
            changed_by_id=split_by_id,
        ))
        ticket.updated_at = now_local()
        ticket.updated_by_id = split_by_id

        db.commit()
    except HTTPException:
        _rollback_and_remove_copies(db, copied_paths)
        raise
    except Exception as e:
        _rollback_and_remove_copies(db, copied_paths)
        logger.exception(f"Error al partir ticket {ticket_id}: {e}")
        raise HTTPException(status_code=500, detail='Error al partir ticket')

    logger.info(
        f"Ticket {ticket_id} partido por usuario {split_by_id}: "
        f"{len(new_tickets)} ticket(s) nuevo(s) ({part_numbers}), {len(copied_paths)} adjunto(s) copiado(s)"
    )
    return ticket, new_tickets


# ==================== VALIDACIÓN ====================
def _validate_part(db: Session, part: dict, number: int) -> dict:
    """
    Valida una parte nueva con las reglas del alta de tickets y devuelve sus
    campos normalizados (título y descripción sin espacios alrededor). No muta
    nada. `number` es su número de parte (el original es la 1).
    """
    from itcj2.apps.helpdesk.utils.catalog_cache import get_area_codes, get_priority_codes

    def invalid(message: str) -> HTTPException:
        return HTTPException(status_code=400, detail=f'Parte {number}: {message}')

    area = part.get('area')
    category_id = part.get('category_id')
    priority = part.get('priority')
    title = (part.get('title') or '').strip()
    description = (part.get('description') or '').strip()

    valid_areas = get_area_codes(db, active_only=True)
    if area not in valid_areas:
        raise invalid(f'Área inválida. Válidas: {sorted(valid_areas)}')

    category = db.get(Category, category_id) if category_id else None
    if not category or not category.is_active:
        raise invalid('Categoría inválida o inactiva')
    if category.area != area:
        raise invalid(f'La categoría no corresponde al área {area}')

    valid_priorities = get_priority_codes(db, active_only=True)
    if priority not in valid_priorities:
        raise invalid(f'Prioridad inválida. Válidas: {sorted(valid_priorities)}')

    if len(title) < _TITLE_MIN_LEN:
        raise invalid(f'El título debe tener al menos {_TITLE_MIN_LEN} caracteres')
    if len(title) > _TITLE_MAX_LEN:
        raise invalid(f'El título no debe exceder {_TITLE_MAX_LEN} caracteres')
    if len(description) < _DESCRIPTION_MIN_LEN:
        raise invalid(f'La descripción debe tener al menos {_DESCRIPTION_MIN_LEN} caracteres')

    return {
        'area': area,
        'category_id': category.id,
        'priority': priority,
        'title': title,
        'description': description,
    }


def _edit_original(db: Session, ticket: Ticket, split_by_id: int, original: dict) -> None:
    """
    Acota el original con `apply_ticket_field_edits` (mismas reglas que "Editar
    ticket": valida solo lo que cambia). Sus 400 llegan como "Ticket original: ...".
    Puede lanzar con campos ya mutados en memoria: el caller hace rollback.
    """
    from itcj2.apps.helpdesk.services.ticket_service import apply_ticket_field_edits

    area = original.get('area')
    category_id = original.get('category_id')
    title = original.get('title')

    # Dos casos que `apply_ticket_field_edits` deja pasar y aquí acabarían mal:
    # un área nueva con la MISMA categoría (quedaría una categoría de otra área;
    # mismo texto que el suyo cuando falta la categoría) y un título de más de
    # 200 caracteres (la BD lo rechaza: 500 en vez de 400).
    if area and area != ticket.area and category_id == ticket.category_id:
        raise HTTPException(
            status_code=400,
            detail='Ticket original: Al cambiar de area debe seleccionar una nueva categoria',
        )
    if title is not None and len(title.strip()) > _TITLE_MAX_LEN:
        raise HTTPException(
            status_code=400,
            detail=f'Ticket original: El título no debe exceder {_TITLE_MAX_LEN} caracteres',
        )

    try:
        apply_ticket_field_edits(
            db, ticket, split_by_id,
            area=area,
            category_id=category_id,
            priority=original.get('priority'),
            title=title,
            description=original.get('description'),
        )
    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=f'Ticket original: {e.detail}') from e


def _inheritable_custom_fields(custom_fields, category) -> dict:
    """
    Campos personalizados que hereda una parte que conserva la categoría del
    original: todos menos los de tipo `file` según la plantilla de esa categoría.
    El archivo de un campo `file` es del original; compartir su ruta tendría el
    mismo problema que los adjuntos.
    """
    if not isinstance(custom_fields, dict) or not custom_fields:
        return {}

    template = (category.field_template if category else None) or {}
    fields = template.get('fields') if isinstance(template, dict) else None
    file_keys = {
        field.get('key')
        for field in (fields or [])
        if isinstance(field, dict) and field.get('type') == 'file'
    }
    return {key: value for key, value in custom_fields.items() if key not in file_keys}


# ==================== COPIA DE ADJUNTOS ====================
def _copy_ticket_attachment(
    db: Session,
    attachment: Attachment,
    part_id: int,
    copied_paths: list[str],
) -> Attachment | None:
    """
    Copia en disco un adjunto inicial del original para la parte `part_id` (mismo
    directorio) y agrega su fila `Attachment`. La ruta nueva queda en
    `copied_paths` para que un fallo posterior la borre. Si el archivo fuente ya
    no está en disco lo omite con un warning: la división sigue sin él.

    Nombre: el del original con su prefijo `{id del original}` cambiado por
    `{part_id}` (`12.jpg` -> `57.jpg`, `12_doc.pdf.gz` -> `57_doc.pdf.gz`); si no
    empieza así, `{part_id}_{nombre}`. Si ya existe, sufijo único antes de la
    extensión: nunca se pisa un archivo ajeno.
    """
    src = attachment.filepath
    if not src or not os.path.isfile(src):
        logger.warning(
            f"Adjunto {attachment.id} del ticket {attachment.ticket_id}: el archivo {src} "
            f"no existe en disco; no se copia a la parte {part_id}"
        )
        return None

    name = os.path.basename(attachment.filename or '') or os.path.basename(src)
    original_prefix = str(attachment.ticket_id)
    if name.startswith(original_prefix):
        base_name = f'{part_id}{name[len(original_prefix):]}'
    else:
        base_name = f'{part_id}_{name}'

    directory = os.path.dirname(src)
    new_name = base_name
    dst = os.path.join(directory, new_name)
    # `lexists`: un symlink roto también cuenta como ocupado (copiar encima
    # escribiría en su destino).
    while os.path.lexists(dst):
        root, ext = _split_extension(base_name)
        new_name = f'{root}_{uuid4().hex[:8]}{ext}'
        dst = os.path.join(directory, new_name)

    # Se registra ANTES de copiar: si la copia truena a medias, el archivo
    # parcial también se limpia.
    copied_paths.append(dst)
    shutil.copy2(src, dst)

    copied = Attachment(
        ticket_id=part_id,
        uploaded_by_id=attachment.uploaded_by_id,
        attachment_type='ticket',
        filename=new_name,
        original_filename=attachment.original_filename,
        filepath=dst,
        mime_type=attachment.mime_type,
        file_size=attachment.file_size,
    )
    db.add(copied)
    return copied


def _split_extension(filename: str) -> tuple[str, str]:
    """
    `os.path.splitext` que trata `.pdf.gz` como UNA extensión: el sufijo único
    queda antes de `.pdf` y la ruta sigue terminando en `.gz`, que es lo que mira
    la descarga para descomprimir.
    """
    root, ext = os.path.splitext(filename)
    if ext.lower() == '.gz':
        inner_root, inner_ext = os.path.splitext(root)
        if inner_ext:
            return inner_root, inner_ext + ext
    return root, ext


def _rollback_and_remove_copies(db: Session, copied_paths: list[str]) -> None:
    """Deshace una división a medias: rollback de la sesión y borrado de las copias."""
    try:
        db.rollback()
    except Exception as e:
        logger.error(f"Error al hacer rollback al partir ticket: {e}")

    for path in copied_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as e:
            logger.error(f"No se pudo borrar la copia de adjunto {path}: {e}")
