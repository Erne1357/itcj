"""
Rutas base para operaciones principales de tickets.
"""
from flask import Blueprint, request, jsonify, g
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.services import ticket_service
from itcj.core.services.authz_service import user_roles_in_app
import logging

logger = logging.getLogger(__name__)

# Sub-blueprint para rutas base de tickets
tickets_base_bp = Blueprint('tickets_base', __name__)


# ==================== CREAR TICKET ====================
@tickets_base_bp.post('')
@tickets_base_bp.post('/')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.create'])
def create_ticket():
    """
    Crea un nuevo ticket de soporte.
    
    Acepta JSON o FormData (si incluye foto)
    
    Body (JSON):
        {
            "area": "DESARROLLO" | "SOPORTE",
            "category_id": int,
            "title": str,
            "description": str,
            "priority": "BAJA" | "MEDIA" | "ALTA" | "URGENTE" (opcional),
            "location": str (opcional),
            "office_folio": str (opcional),
            "inventory_item_ids": [int] (opcional) - Array de IDs de equipos,
            "requester_id": int (opcional) - ID del usuario solicitante (solo para admins/comp_center)
        }

    Body (FormData):
        Los mismos campos + "photo": archivo de imagen
        Para inventory_item_ids usar: inventory_item_ids[] repetido o JSON string

    Returns:
        201: Ticket creado exitosamente
        400: Datos inválidos
        403: No autorizado para crear tickets para otros
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    # Detectar si es FormData (multipart) o JSON
    if request.content_type and 'multipart/form-data' in request.content_type:
        # Extraer datos del FormData
        data = {}
        for key in request.form:
            value = request.form[key]
            # Convertir a int si es necesario
            if key in ['category_id', 'requester_id']:
                data[key] = int(value) if value else None
            elif key == 'inventory_item_ids':
                # Puede venir como JSON string
                try:
                    import json
                    data[key] = json.loads(value)
                except:
                    data[key] = []
            else:
                data[key] = value

        # Si viene como array HTML (inventory_item_ids[])
        if 'inventory_item_ids[]' in request.form:
            data['inventory_item_ids'] = request.form.getlist('inventory_item_ids[]', type=int)

        # Obtener archivo de foto
        photo_file = request.files.get('photo')

        # Extraer custom_fields y archivos de custom fields
        custom_fields = {}
        custom_field_files = {}

        # Extraer custom_fields JSON si está presente
        if 'custom_fields' in request.form:
            try:
                import json
                custom_fields = json.loads(request.form['custom_fields'])
            except:
                pass

        # Extraer valores individuales de custom fields desde form
        for key in request.form:
            if key.startswith('custom_field_') and not key.startswith('custom_field_file_'):
                field_key = key.replace('custom_field_', '')
                custom_fields[field_key] = request.form[key]

        # Extraer archivos de custom fields
        for key in request.files:
            if key.startswith('custom_field_'):
                field_key = key.replace('custom_field_', '')
                custom_field_files[field_key] = request.files[key]
    else:
        # JSON normal
        data = request.get_json()
        photo_file = None
        custom_fields = data.get('custom_fields', {})
        custom_field_files = {}
    
    # Validar campos requeridos
    required_fields = ['area', 'category_id', 'title', 'description']
    missing_fields = [field for field in required_fields if field not in data or not data[field]]
    
    if missing_fields:
        return jsonify({
            'error': 'missing_fields',
            'message': f'Faltan campos requeridos: {", ".join(missing_fields)}'
        }), 400
    
    # Validar longitudes
    if len(data['title'].strip()) < 5:
        return jsonify({
            'error': 'invalid_title',
            'message': 'El título debe tener al menos 5 caracteres'
        }), 400
    
    if len(data['description'].strip()) < 20:
        return jsonify({
            'error': 'invalid_description',
            'message': 'La descripción debe tener al menos 20 caracteres'
        }), 400
    
    # Validar inventory_item_ids si vienen
    inventory_item_ids = data.get('inventory_item_ids', [])
    if inventory_item_ids:
        if not isinstance(inventory_item_ids, list):
            return jsonify({
                'error': 'invalid_equipment_format',
                'message': 'inventory_item_ids debe ser un array'
            }), 400

        from itcj.apps.helpdesk.models import InventoryItem
        for item_id in inventory_item_ids:
            item = InventoryItem.query.get(item_id)
            if not item or not item.is_active:
                return jsonify({
                    'error': 'invalid_equipment',
                    'message': f'El equipo {item_id} no es válido'
                }), 400

    # Determinar el requester_id
    requester_id = data.get('requester_id')

    if requester_id and requester_id != user_id:
        # El usuario está intentando crear un ticket para otra persona
        # Verificar que tenga permiso
        can_create_for_other = False

        if 'admin' in user_roles:
            can_create_for_other = True
        else:
            # Verificar si pertenece al Centro de Cómputo
            from itcj.core.models.position import UserPosition
            user_positions = UserPosition.query.filter_by(
                user_id=user_id,
                is_active=True
            ).all()

            for user_position in user_positions:
                if user_position.position and user_position.position.department:
                    if user_position.position.department.code == 'comp_center':
                        can_create_for_other = True
                        break

        if not can_create_for_other:
            return jsonify({
                'error': 'forbidden',
                'message': 'No tienes permiso para crear tickets para otros usuarios'
            }), 403

        # Verificar que el requester existe y está activo
        from itcj.core.models.user import User
        requester = User.query.get(requester_id)
        if not requester or not requester.is_active:
            return jsonify({
                'error': 'invalid_requester',
                'message': 'El usuario solicitante no es válido'
            }), 400
    else:
        # Crear ticket para el mismo usuario
        requester_id = user_id

    # ==================== CHECK TICKETS SIN EVALUAR ====================
    from itcj.apps.helpdesk.models.ticket import Ticket
    MAX_UNRATED_TICKETS = 3
    unrated_count = Ticket.query.filter(
        Ticket.requester_id == requester_id,
        Ticket.status.in_(['RESOLVED_SUCCESS', 'RESOLVED_FAILED']),
        Ticket.rating_attention.is_(None)
    ).count()
    if unrated_count >= MAX_UNRATED_TICKETS:
        return jsonify({
            'error': 'ticket_creation_restricted',
            'message': (
                f'Tienes {unrated_count} tickets sin evaluar. '
                f'Debes evaluar tus tickets resueltos antes de crear uno nuevo.'
            )
        }), 403

    try:
        ticket = ticket_service.create_ticket(
            requester_id=requester_id,
            area=data['area'],
            category_id=data['category_id'],
            title=data['title'].strip(),
            description=data['description'].strip(),
            priority=data.get('priority', 'MEDIA'),
            location=data.get('location'),
            office_folio=data.get('office_folio'),
            inventory_item_ids=inventory_item_ids,
            photo_file=photo_file,
            custom_fields=custom_fields,
            custom_field_files=custom_field_files,
            created_by_id=user_id
        )

        logger.info(f"Ticket {ticket.ticket_number} creado por usuario {user_id}")

        # Notificar a secretaria/admins sobre el nuevo ticket
        from itcj.apps.helpdesk.services.notification_helper import HelpdeskNotificationHelper
        from itcj.core.extensions import db
        try:
            HelpdeskNotificationHelper.notify_ticket_created(ticket)
            db.session.commit()
        except Exception as notif_error:
            logger.error(f"Error al enviar notificación de ticket creado: {notif_error}")
            # No fallar la creación del ticket por error en notificación

        return jsonify({
            'message': 'Ticket creado exitosamente',
            'ticket': ticket.to_dict(include_relations=True)
        }), 201

    except Exception as e:
        logger.error(f"Error al crear ticket: {e}")
        return jsonify({
            'error': 'creation_failed',
            'message': str(e)
        }), 500


# ==================== LISTAR TICKETS ====================
@tickets_base_bp.get('')
@tickets_base_bp.get('/')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def list_tickets():
    """
    Lista tickets según filtros y permisos del usuario.
    
    Query params:
        - status: Filtrar por estado (puede ser uno o varios separados por comas, ej: 'PENDING' o 'ASSIGNED,IN_PROGRESS')
        - area: Filtrar por área (DESARROLLO/SOPORTE)
        - priority: Filtrar por prioridad
        - assigned_to_me: true/false - Solo asignados a mí
        - assigned_to_team: desarrollo/soporte - Solo asignados al equipo (sin usuario específico)
        - created_by_me: true/false - Solo donde soy el requester (quien solicitó el ticket)
        - department_id: Filtrar por departamento
        - search: Buscar por título, número de ticket o descripción
        - page: Número de página (default: 1)
        - per_page: Items por página (default: 20, max: 100)
    
    Returns:
        200: Lista de tickets con paginación
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    # Obtener parámetros de query
    status = request.args.get('status')
    # Procesar múltiples estados separados por comas
    if status:
        status_list = [s.strip().upper() for s in status.split(',') if s.strip()]
        status = status_list if status_list else None
    
    area = request.args.get('area')
    priority = request.args.get('priority')
    assigned_to_me = request.args.get('assigned_to_me', 'false').lower() == 'true'
    assigned_to_team = request.args.get('assigned_to_team')
    created_by_me = request.args.get('created_by_me', 'false').lower() == 'true'
    department_id = request.args.get('department_id', type=int)
    search = request.args.get('search', '').strip() or None
    page = request.args.get('page', 1, type=int)
    # Permitir per_page alto para admins/técnicos (0 o -1 = sin límite, max 1000)
    requested_per_page = request.args.get('per_page', 20, type=int)

    include_metrics = request.args.get('include_metrics', 'false').lower() == 'true'
    if requested_per_page <= 0:
        # Sin límite (usar 1000 como máximo práctico)
        per_page = 1000
    else:
        # Límite normal de 100 para usuarios regulares, 1000 para admins/técnicos
        if 'admin' in user_roles or 'tech_desarrollo' in user_roles or 'tech_soporte' in user_roles:
            per_page = min(requested_per_page, 1000)
        else:
            per_page = min(requested_per_page, 100)
    
    try:
        result = ticket_service.list_tickets(
            user_id=user_id,
            user_roles=user_roles,
            status=status,
            area=area,
            priority=priority,
            assigned_to_me=assigned_to_me,
            assigned_to_team=assigned_to_team,
            created_by_me=created_by_me,
            department_id=department_id,
            search=search,
            page=page,
            per_page=per_page,
            include_metrics=include_metrics
        )
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error al listar tickets: {e}")
        return jsonify({
            'error': 'list_failed',
            'message': str(e)
        }), 500


# ==================== OBTENER TICKET POR ID ====================
@tickets_base_bp.get('/<int:ticket_id>')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def get_ticket(ticket_id):
    """
    Obtiene un ticket específico por ID.
    
    Params:
        ticket_id: ID del ticket
    
    Returns:
        200: Ticket encontrado
        403: Sin permiso para ver el ticket
        404: Ticket no encontrado
    """
    user_id = int(g.current_user['sub'])
    
    try:
        ticket = ticket_service.get_ticket_by_id(
            ticket_id=ticket_id,
            user_id=user_id,
            check_permissions=True
        )
        
        return jsonify({
            'ticket': ticket.to_dict(include_relations=True)
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener ticket {ticket_id}: {e}")
        # Los errores de abort ya manejan el código de estado
        raise


# ==================== INICIAR TRABAJO EN TICKET ====================
@tickets_base_bp.post('/<int:ticket_id>/start')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.resolve'])
def start_ticket(ticket_id):
    """
    Técnico marca que comenzó a trabajar en el ticket (ASSIGNED → IN_PROGRESS).
    
    Params:
        ticket_id: ID del ticket
    
    Returns:
        200: Estado actualizado
        400: No se puede iniciar en el estado actual
        403: No tienes permiso
    """
    user_id = int(g.current_user['sub'])
    
    try:
        # Verificar que el ticket esté asignado al técnico
        ticket = ticket_service.get_ticket_by_id(ticket_id, user_id, check_permissions=True)
        
        if ticket.assigned_to_user_id != user_id:
            return jsonify({
                'error': 'not_assigned',
                'message': 'El ticket no está asignado a ti'
            }), 403
        
        # Cambiar estado a IN_PROGRESS
        ticket = ticket_service.change_status(
            ticket_id=ticket_id,
            new_status='IN_PROGRESS',
            changed_by_id=user_id,
            notes='Técnico comenzó a trabajar en el ticket'
        )

        logger.info(f"Ticket {ticket.ticket_number} iniciado por técnico {user_id}")

        # Notificar al solicitante que el trabajo comenzó
        from itcj.apps.helpdesk.services.notification_helper import HelpdeskNotificationHelper
        from itcj.core.extensions import db
        try:
            HelpdeskNotificationHelper.notify_ticket_in_progress(ticket)
            db.session.commit()
        except Exception as notif_error:
            logger.error(f"Error al enviar notificación de ticket iniciado: {notif_error}")

        return jsonify({
            'message': 'Ticket iniciado exitosamente',
            'ticket': ticket.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Error al iniciar ticket {ticket_id}: {e}")
        raise


# ==================== RESOLVER TICKET ====================
@tickets_base_bp.post('/<int:ticket_id>/resolve')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.resolve'])
def resolve_ticket(ticket_id):
    """
    Técnico resuelve el ticket.

    Body:
        {
            "success": bool,
            "resolution_notes": str,  (mínimo 10 caracteres)
            "time_invested_minutes": int,  (requerido, minutos)
            "maintenance_type": str,  ("PREVENTIVO" o "CORRECTIVO")
            "service_origin": str,  ("INTERNO" o "EXTERNO")
            "observations": str  (opcional)
        }

    Returns:
        200: Ticket resuelto
        400: Datos inválidos
        403: No tienes permiso
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])

    # Validar campos requeridos
    required_fields = ['success', 'resolution_notes', 'time_invested_minutes', 'maintenance_type', 'service_origin']
    missing = [f for f in required_fields if f not in data or data[f] is None]
    if missing:
        return jsonify({
            'error': 'missing_fields',
            'message': f'Faltan campos requeridos: {", ".join(missing)}'
        }), 400

    try:
        ticket = ticket_service.resolve_ticket(
            ticket_id=ticket_id,
            resolved_by_id=user_id,
            success=data['success'],
            resolution_notes=data['resolution_notes'],
            time_invested_minutes=data['time_invested_minutes'],
            maintenance_type=data['maintenance_type'],
            service_origin=data['service_origin'],
            observations=data.get('observations')
        )
        
        logger.info(f"Ticket {ticket.ticket_number} resuelto por técnico {user_id}")

        # Notificar al solicitante que el ticket fue resuelto
        from itcj.apps.helpdesk.services.notification_helper import HelpdeskNotificationHelper
        from itcj.core.extensions import db
        try:
            HelpdeskNotificationHelper.notify_ticket_resolved(ticket)
            db.session.commit()
        except Exception as notif_error:
            logger.error(f"Error al enviar notificación de ticket resuelto: {notif_error}")

        return jsonify({
            'message': 'Ticket resuelto exitosamente',
            'ticket': ticket.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Error al resolver ticket {ticket_id}: {e}")
        raise


# ==================== CALIFICAR TICKET ====================
@tickets_base_bp.post('/<int:ticket_id>/rate')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def rate_ticket(ticket_id):
    """
    Usuario califica el servicio del ticket mediante encuesta.
    
    Body:
        {
            "rating_attention": int,  # 1-5 estrellas (obligatorio) - Calidad de atención
            "rating_speed": int,  # 1-5 estrellas (obligatorio) - Rapidez del servicio
            "rating_efficiency": bool,  # true/false (obligatorio) - Eficiencia del servicio
            "comment": str (opcional)  # Sugerencias y comentarios
        }
    
    Returns:
        200: Ticket calificado
        400: Datos inválidos
        403: No eres el requester o ya fue calificado
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    
    # Validar campos obligatorios
    if 'rating_attention' not in data or 'rating_speed' not in data or 'rating_efficiency' not in data:
        return jsonify({'error': 'Los campos rating_attention, rating_speed y rating_efficiency son obligatorios'}), 400
    
    # Validar rating_attention
    try:
        rating_attention = int(data['rating_attention'])
    except (ValueError, TypeError):
        return jsonify({'error': 'rating_attention debe ser un número entero'}), 400
    
    if rating_attention < 1 or rating_attention > 5:
        return jsonify({'error': 'rating_attention debe estar entre 1 y 5'}), 400
    
    # Validar rating_speed
    try:
        rating_speed = int(data['rating_speed'])
    except (ValueError, TypeError):
        return jsonify({'error': 'rating_speed debe ser un número entero'}), 400
    
    if rating_speed < 1 or rating_speed > 5:
        return jsonify({'error': 'rating_speed debe estar entre 1 y 5'}), 400
    
    # Validar rating_efficiency
    try:
        rating_efficiency = bool(data['rating_efficiency'])
    except (ValueError, TypeError):
        return jsonify({'error': 'rating_efficiency debe ser un valor booleano'}), 400
    
    try:
        ticket = ticket_service.rate_ticket(
            ticket_id=ticket_id,
            requester_id=user_id,
            rating_attention=rating_attention,
            rating_speed=rating_speed,
            rating_efficiency=rating_efficiency,
            comment=data.get('comment')
        )
        
        logger.info(f"Ticket {ticket.ticket_number} calificado - Atención: {rating_attention}, Rapidez: {rating_speed}, Eficiencia: {rating_efficiency}")

        # Notificar al técnico de su calificación
        from itcj.apps.helpdesk.services.notification_helper import HelpdeskNotificationHelper
        from itcj.core.extensions import db
        try:
            HelpdeskNotificationHelper.notify_ticket_rated(ticket)
            db.session.commit()
        except Exception as notif_error:
            logger.error(f"Error al enviar notificación de ticket calificado: {notif_error}")

        return jsonify({
            'message': 'Ticket calificado exitosamente',
            'ticket': ticket.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Error al calificar ticket {ticket_id}: {e}")
        raise


# ==================== CANCELAR TICKET ====================
@tickets_base_bp.post('/<int:ticket_id>/cancel')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def cancel_ticket(ticket_id):
    """
    Usuario cancela su ticket.
    
    Body:
        {
            "reason": str (opcional)  # Razón de cancelación
        }
    
    Returns:
        200: Ticket cancelado
        403: No eres el requester
        400: No se puede cancelar en el estado actual
    """
    data = request.get_json() or {}
    user_id = int(g.current_user['sub'])
    
    try:
        ticket = ticket_service.cancel_ticket(
            ticket_id=ticket_id,
            user_id=user_id,
            reason=data.get('reason')
        )
        
        logger.info(f"Ticket {ticket.ticket_number} cancelado por usuario {user_id}")

        # Notificar al técnico asignado si existe
        from itcj.apps.helpdesk.services.notification_helper import HelpdeskNotificationHelper
        from itcj.core.extensions import db
        try:
            HelpdeskNotificationHelper.notify_ticket_canceled(ticket)
            db.session.commit()
        except Exception as notif_error:
            logger.error(f"Error al enviar notificación de ticket cancelado: {notif_error}")

        return jsonify({
            'message': 'Ticket cancelado exitosamente',
            'ticket': ticket.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Error al cancelar ticket {ticket_id}: {e}")
        raise


# ==================== EDITAR TICKET PENDIENTE ====================
@tickets_base_bp.patch('/<int:ticket_id>')
@api_app_required('helpdesk', perms=['helpdesk.tickets.api.read.own'])
def update_ticket(ticket_id):
    """
    Edita campos de un ticket en estado PENDING.
    Solo administradores y secretaria de centro de computo pueden editar.

    Body:
        {
            "area": "DESARROLLO" | "SOPORTE" (opcional),
            "category_id": int (opcional),
            "priority": "BAJA" | "MEDIA" | "ALTA" | "URGENTE" (opcional),
            "title": str (opcional),
            "description": str (opcional),
            "location": str (opcional)
        }

    Reglas:
        - Si cambia area, category_id es obligatorio (nueva categoria del area)
        - Si cambia category_id, se borran custom_fields
        - Se registran todos los cambios en TicketEditLog

    Returns:
        200: Ticket actualizado
        400: Datos invalidos o transicion no permitida
        403: Sin permiso
        404: Ticket no encontrado
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')

    # Verificar permisos (admin o secretary_comp_center)
    from itcj.core.services.authz_service import _get_users_with_position
    secretary_comp_center = _get_users_with_position(['secretary_comp_center'])

    if 'admin' not in user_roles and user_id not in secretary_comp_center:
        return jsonify({
            'error': 'forbidden',
            'message': 'No tienes permiso para editar tickets'
        }), 403

    try:
        ticket = ticket_service.update_pending_ticket(
            ticket_id=ticket_id,
            updated_by_id=user_id,
            area=data.get('area'),
            category_id=data.get('category_id'),
            priority=data.get('priority'),
            title=data.get('title'),
            description=data.get('description'),
            location=data.get('location')
        )

        logger.info(f"Ticket {ticket.ticket_number} editado por usuario {user_id}")

        return jsonify({
            'message': 'Ticket actualizado exitosamente',
            'ticket': ticket.to_dict(include_relations=True)
        }), 200

    except Exception as e:
        logger.error(f"Error al editar ticket {ticket_id}: {e}")
        raise