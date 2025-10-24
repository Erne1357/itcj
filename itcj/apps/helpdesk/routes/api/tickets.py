from flask import request, jsonify, g
from itcj.core.utils.decorators import api_app_required
from itcj.apps.helpdesk.services import ticket_service
from itcj.core.services.authz_service import user_roles_in_app
from . import tickets_api_bp
import logging

logger = logging.getLogger(__name__)


# ==================== CREAR TICKET ====================
@tickets_api_bp.post('')
@api_app_required('helpdesk', perms=['helpdesk.create'])
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
            "inventory_item_id": int (opcional)
        }
    
    Body (FormData):
        Los mismos campos + "photo": archivo de imagen
    
    Returns:
        201: Ticket creado exitosamente
        400: Datos inválidos
    """
    user_id = int(g.current_user['sub'])
    
    # Detectar si es FormData (multipart) o JSON
    if request.content_type and 'multipart/form-data' in request.content_type:
        # Extraer datos del FormData
        data = {}
        for key in request.form:
            value = request.form[key]
            # Convertir a int si es necesario
            if key in ['category_id', 'inventory_item_id']:
                data[key] = int(value) if value else None
            else:
                data[key] = value
        
        # Obtener archivo de foto
        photo_file = request.files.get('photo')
    else:
        # JSON normal
        data = request.get_json()
        photo_file = None
    
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
    
    # Validar inventory_item_id si viene
    inventory_item_id = data.get('inventory_item_id')
    if inventory_item_id:
        from itcj.apps.helpdesk.models import InventoryItem
        item = InventoryItem.query.get(inventory_item_id)
        if not item or not item.is_active:
            return jsonify({
                'error': 'invalid_equipment',
                'message': 'El equipo seleccionado no es válido'
            }), 400
    
    try:
        ticket = ticket_service.create_ticket(
            requester_id=user_id,
            area=data['area'],
            category_id=data['category_id'],
            title=data['title'].strip(),
            description=data['description'].strip(),
            priority=data.get('priority', 'MEDIA'),
            location=data.get('location'),
            office_folio=data.get('office_folio'),
            inventory_item_id=inventory_item_id,
            photo_file=photo_file  # ← NUEVO
        )
        
        logger.info(f"Ticket {ticket.ticket_number} creado por usuario {user_id}")
        
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
@tickets_api_bp.get('')
@api_app_required('helpdesk', perms=['helpdesk.own.read'])
def list_tickets():
    """
    Lista tickets según filtros y permisos del usuario.
    
    Query params:
        - status: Filtrar por estado (puede ser uno o varios separados por comas, ej: 'PENDING' o 'ASSIGNED,IN_PROGRESS')
        - area: Filtrar por área (DESARROLLO/SOPORTE)
        - priority: Filtrar por prioridad
        - assigned_to_me: true/false - Solo asignados a mí
        - created_by_me: true/false - Solo creados por mí
        - department_id: Filtrar por departamento
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
    created_by_me = request.args.get('created_by_me', 'false').lower() == 'true'
    department_id = request.args.get('department_id', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    
    try:
        result = ticket_service.list_tickets(
            user_id=user_id,
            user_roles=user_roles,
            status=status,
            area=area,
            priority=priority,
            assigned_to_me=assigned_to_me,
            created_by_me=created_by_me,
            department_id=department_id,
            page=page,
            per_page=per_page
        )
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error al listar tickets: {e}")
        return jsonify({
            'error': 'list_failed',
            'message': str(e)
        }), 500


# ==================== OBTENER TICKET POR ID ====================
@tickets_api_bp.get('/<int:ticket_id>')
@api_app_required('helpdesk', perms=['helpdesk.own.read'])
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
            'ticket': ticket.to_dict(include_relations=True, include_metrics=True)
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener ticket {ticket_id}: {e}")
        # Los errores de abort ya manejan el código de estado
        raise


# ==================== INICIAR TRABAJO EN TICKET ====================
@tickets_api_bp.post('/<int:ticket_id>/start')
@api_app_required('helpdesk', perms=['helpdesk.resolve'])
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
                'message': 'Este ticket no está asignado a ti'
            }), 403
        
        # Cambiar estado a IN_PROGRESS
        ticket = ticket_service.change_status(
            ticket_id=ticket_id,
            new_status='IN_PROGRESS',
            changed_by_id=user_id,
            notes='Técnico comenzó a trabajar en el ticket'
        )
        
        logger.info(f"Ticket {ticket.ticket_number} iniciado por técnico {user_id}")
        
        # TODO: Emitir evento SSE
        
        return jsonify({
            'message': 'Ticket iniciado',
            'ticket': ticket.to_dict(include_relations=True)
        }), 200
        
    except Exception as e:
        logger.error(f"Error al iniciar ticket {ticket_id}: {e}")
        raise


# ==================== RESOLVER TICKET ====================
@tickets_api_bp.post('/<int:ticket_id>/resolve')
@api_app_required('helpdesk', perms=['helpdesk.resolve'])
def resolve_ticket(ticket_id):
    """
    Técnico resuelve el ticket.
    
    Body:
        {
            "success": bool,  # true si fue exitoso, false si no se pudo resolver
            "resolution_notes": str,  # Notas de resolución (mínimo 10 caracteres)
            "time_invested_minutes": int (opcional)  # Tiempo invertido en minutos
        }
    
    Returns:
        200: Ticket resuelto
        400: Datos inválidos
        403: No tienes permiso
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    
    # Validar campos requeridos
    if 'success' not in data or 'resolution_notes' not in data:
        return jsonify({
            'error': 'missing_fields',
            'message': 'Se requieren los campos: success, resolution_notes'
        }), 400
    
    try:
        ticket = ticket_service.resolve_ticket(
            ticket_id=ticket_id,
            resolved_by_id=user_id,
            success=data['success'],
            resolution_notes=data['resolution_notes'],
            time_invested_minutes=data.get('time_invested_minutes')
        )
        
        logger.info(f"Ticket {ticket.ticket_number} resuelto por técnico {user_id}")
        
        # TODO: Emitir evento SSE para notificar al usuario
        # from itcj.apps.helpdesk.services.notification_service import notify_ticket_resolved
        # notify_ticket_resolved(ticket)
        
        return jsonify({
            'message': 'Ticket resuelto exitosamente',
            'ticket': ticket.to_dict(include_relations=True, include_metrics=True)
        }), 200
        
    except Exception as e:
        logger.error(f"Error al resolver ticket {ticket_id}: {e}")
        raise


# ==================== CALIFICAR TICKET ====================
@tickets_api_bp.post('/<int:ticket_id>/rate')
@api_app_required('helpdesk', perms=['helpdesk.own.read'])
def rate_ticket(ticket_id):
    """
    Usuario califica el servicio del ticket.
    
    Body:
        {
            "rating": int,  # 1-5 estrellas
            "comment": str (opcional)  # Comentario adicional
        }
    
    Returns:
        200: Ticket calificado
        400: Datos inválidos
        403: No eres el requester o ya fue calificado
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    
    # Validar rating
    if 'rating' not in data:
        return jsonify({
            'error': 'missing_rating',
            'message': 'Se requiere el campo rating'
        }), 400
    
    try:
        rating = int(data['rating'])
    except (ValueError, TypeError):
        return jsonify({
            'error': 'invalid_rating',
            'message': 'El rating debe ser un número entero'
        }), 400
    
    if rating < 1 or rating > 5:
        return jsonify({
            'error': 'invalid_rating_range',
            'message': 'El rating debe estar entre 1 y 5'
        }), 400
    
    try:
        ticket = ticket_service.rate_ticket(
            ticket_id=ticket_id,
            requester_id=user_id,
            rating=rating,
            comment=data.get('comment')
        )
        
        logger.info(f"Ticket {ticket.ticket_number} calificado con {rating} estrellas")
        
        # TODO: Emitir evento SSE
        # from itcj.apps.helpdesk.services.notification_service import notify_ticket_rated
        # notify_ticket_rated(ticket)
        
        return jsonify({
            'message': 'Gracias por tu calificación',
            'ticket': ticket.to_dict(include_relations=True)
        }), 200
        
    except Exception as e:
        logger.error(f"Error al calificar ticket {ticket_id}: {e}")
        raise


# ==================== CANCELAR TICKET ====================
@tickets_api_bp.post('/<int:ticket_id>/cancel')
@api_app_required('helpdesk', perms=['helpdesk.own.read'])
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
        
        # TODO: Emitir evento SSE
        
        return jsonify({
            'message': 'Ticket cancelado',
            'ticket': ticket.to_dict(include_relations=True)
        }), 200
        
    except Exception as e:
        logger.error(f"Error al cancelar ticket {ticket_id}: {e}")
        raise


# ==================== OBTENER COMENTARIOS ====================
@tickets_api_bp.get('/<int:ticket_id>/comments')
@api_app_required('helpdesk', perms=['helpdesk.own.read'])
def get_comments(ticket_id):
    """
    Obtiene los comentarios de un ticket.
    Filtra comentarios internos según permisos del usuario.
    
    Returns:
        200: Lista de comentarios
        403: Sin permiso para ver el ticket
        404: Ticket no encontrado
    """
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    try:
        # Verificar que pueda ver el ticket
        ticket = ticket_service.get_ticket_by_id(ticket_id, user_id, check_permissions=True)
        
        # Determinar si puede ver comentarios internos
        can_see_internal = any(role in user_roles for role in ['admin', 'secretary', 'tech_desarrollo', 'tech_soporte'])
        
        # Obtener comentarios
        from itcj.apps.helpdesk.models import Comment
        query = Comment.query.filter_by(ticket_id=ticket_id)
        
        # Filtrar internos si no tiene permiso
        if not can_see_internal:
            query = query.filter_by(is_internal=False)
        
        comments = query.order_by(Comment.created_at.asc()).all()
        
        return jsonify({
            'comments': [c.to_dict() for c in comments]
        }), 200
        
    except Exception as e:
        logger.error(f"Error al obtener comentarios del ticket {ticket_id}: {e}")
        raise


# ==================== AGREGAR COMENTARIO ====================
@tickets_api_bp.post('/<int:ticket_id>/comments')
@api_app_required('helpdesk', perms=['helpdesk.comment'])
def add_comment(ticket_id):
    """
    Agrega un comentario a un ticket.
    
    Body:
        {
            "content": str,  # Contenido del comentario
            "is_internal": bool (opcional, default: false)  # Si es nota interna (solo staff)
        }
    
    Returns:
        201: Comentario creado
        400: Datos inválidos
        403: Sin permiso para comentar o crear notas internas
    """
    data = request.get_json()
    user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(user_id, 'helpdesk')
    
    if 'content' not in data:
        return jsonify({
            'error': 'missing_content',
            'message': 'Se requiere el campo content'
        }), 400
    
    # Validar si puede crear comentarios internos
    is_internal = data.get('is_internal', False)
    if is_internal:
        can_create_internal = any(role in user_roles for role in ['admin', 'secretary', 'tech_desarrollo', 'tech_soporte'])
        if not can_create_internal:
            return jsonify({
                'error': 'forbidden_internal',
                'message': 'No tienes permiso para crear comentarios internos'
            }), 403
    
    try:
        comment = ticket_service.add_comment(
            ticket_id=ticket_id,
            author_id=user_id,
            content=data['content'],
            is_internal=is_internal
        )
        
        logger.info(f"Comentario agregado al ticket {ticket_id} por usuario {user_id}")
        
        # TODO: Emitir evento SSE
        # from itcj.apps.helpdesk.services.notification_service import notify_comment_added
        # notify_comment_added(ticket_id, comment)
        
        return jsonify({
            'message': 'Comentario agregado',
            'comment': comment.to_dict()
        }), 201
        
    except Exception as e:
        logger.error(f"Error al agregar comentario al ticket {ticket_id}: {e}")
        raise