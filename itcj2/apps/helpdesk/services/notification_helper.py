"""
Helper de Notificaciones para Helpdesk

Proporciona métodos para crear notificaciones en los diferentes eventos del ciclo de vida de tickets.
Incluye broadcasts WebSocket para actualizaciones en tiempo real.

Fase 6.5: Las plantillas de título y cuerpo se cargan desde la BD (NotificationTemplate)
y se renderizan con Jinja2. Si la plantilla no existe, está inactiva, o falla la renderización,
se usa el string hardcoded como fallback para preservar el comportamiento previo.
"""
import logging
from typing import Optional

from jinja2 import Environment, DebugUndefined, TemplateSyntaxError
from sqlalchemy.orm import Session

from itcj2.core.services.notification_service import NotificationService
from itcj2.core.models.user import User
from itcj2.core.services.authz_service import _get_users_with_position
from itcj2.utils import async_broadcast as _async_broadcast

logger = logging.getLogger(__name__)

# ==================== JINJA2 ENV ====================

_jinja_env = Environment(autoescape=False, undefined=DebugUndefined)


# ==================== HELPERS DE RENDERIZADO ====================

def _safe_render(template_str: str, context: dict) -> str:
    """Renderiza una cadena Jinja2 capturando errores. Devuelve template_str si falla."""
    try:
        return _jinja_env.from_string(template_str).render(**context)
    except (TemplateSyntaxError, Exception) as e:
        logger.warning(f"Error al renderizar fragmento de plantilla: {e}")
        return template_str


def _render_notification(
    db,
    code: str,
    context: dict,
    fallback_title: str,
    fallback_body: str,
) -> tuple[str, str]:
    """
    Carga la plantilla por code desde el cache de BD y la renderiza con Jinja2.

    Si la plantilla no existe en BD, está inactiva, o produce un error de sintaxis,
    devuelve (fallback_title, fallback_body) — los strings hardcoded originales.

    Returns:
        (title, body)
    """
    from itcj2.apps.helpdesk.utils.catalog_cache import get_notification_template

    try:
        tpl = get_notification_template(db, code)
        if not tpl or not tpl.get('is_active'):
            logger.info(f"Notificación '{code}' usó fallback (template no activo o inexistente)")
            return fallback_title, fallback_body

        subject_template = tpl.get('subject_template')
        body_template = tpl.get('body_template')

        title = _safe_render(subject_template, context) if subject_template else fallback_title
        body = _safe_render(body_template, context) if body_template else fallback_body

        logger.info(f"Notificación '{code}' renderizada (template BD activo)")
        return title, body

    except Exception as e:
        logger.warning(f"Falla al renderizar plantilla '{code}': {e}. Usando fallback.")
        return fallback_title, fallback_body


def _model_to_context(obj) -> dict:
    """
    Snapshot superficial de un modelo SQLAlchemy para uso en plantillas Jinja2.
    No navega relationships para evitar lazy-load inesperado.
    """
    from itcj2.apps.helpdesk.models.ticket import Ticket
    from itcj2.apps.helpdesk.models.comment import Comment

    if isinstance(obj, Ticket):
        return {
            'id': obj.id,
            'ticket_number': obj.ticket_number,
            'title': obj.title,
            'description': obj.description,
            'status': obj.status,
            'priority': obj.priority,
            'area': obj.area,
            'location': obj.location,
            'created_at': obj.created_at.isoformat() if obj.created_at else None,
        }
    if isinstance(obj, User):
        return {
            'id': obj.id,
            'name': getattr(obj, 'full_name', None) or getattr(obj, 'username', None) or str(obj.id),
            'email': getattr(obj, 'email', None),
        }
    if isinstance(obj, Comment):
        return {
            'id': obj.id,
            'content': obj.content,
            'is_internal': obj.is_internal,
            'created_at': obj.created_at.isoformat() if obj.created_at else None,
        }
    # Fallback genérico para tipos no previstos
    return {'id': getattr(obj, 'id', None), 'str': str(obj)}


def _build_context(**kwargs) -> dict:
    """
    Construye el contexto Jinja2 para renderizar plantillas.
    Los modelos SQLAlchemy se convierten a dicts superficiales para evitar
    lazy-load de relationships desde dentro de la plantilla.
    """
    ctx = {}
    for key, obj in kwargs.items():
        if obj is None:
            ctx[key] = None
        elif hasattr(obj, '__tablename__'):  # SQLAlchemy model
            ctx[key] = _model_to_context(obj)
        else:
            ctx[key] = obj
    return ctx


# ==================== HELPER PRINCIPAL ====================

class HelpdeskNotificationHelper:
    """Helper para crear notificaciones de eventos de helpdesk"""

    @staticmethod
    def notify_ticket_created(db: Session, ticket):
        """
        Notifica a secretaria/admins cuando se crea un nuevo ticket.
        """
        try:
            from itcj2.sockets.helpdesk import broadcast_ticket_created

            recipients = set()

            users_by_position = _get_users_with_position(db, ['secretary_comp_center']) or []
            for u in users_by_position:
                if getattr(u, 'id', None):
                    recipients.add(u.id)

            logger.warning(f"Recipients for TICKET_CREATED: {users_by_position}")

            recipients = list(recipients)

            fallback_title = f'Nuevo ticket #{ticket.ticket_number}'
            fallback_body = f'{ticket.title} - Prioridad: {ticket.priority}'

            context = _build_context(
                ticket=ticket,
                requester=ticket.requester,
            )
            title, body = _render_notification(
                db, 'ticket_created', context, fallback_title, fallback_body
            )

            for user_id in recipients:
                NotificationService.create(
                    db=db,
                    user_id=user_id,
                    app_name='helpdesk',
                    type='TICKET_CREATED',
                    title=title,
                    body=body,
                    data={
                        'ticket_id': ticket.id,
                        'url': f'/help-desk/user/tickets/{ticket.id}',
                        'priority': ticket.priority,
                        'area': ticket.area,
                        'requester': ticket.requester.full_name if ticket.requester else 'Desconocido'
                    },
                    ticket_id=ticket.id
                )

            logger.info(
                f"Notificación TICKET_CREATED enviada a {len(recipients)} usuarios para ticket #{ticket.ticket_number}"
            )

            _async_broadcast(broadcast_ticket_created({
                'id': ticket.id,
                'ticket_number': ticket.ticket_number,
                'title': ticket.title,
                'area': ticket.area,
                'priority': ticket.priority,
                'status': ticket.status,
                'requester': ticket.requester.full_name if ticket.requester else 'Desconocido',
                'department_id': ticket.requester_department_id
            }))

        except Exception as e:
            logger.error(
                f"Error enviando notificación TICKET_CREATED para ticket #{ticket.ticket_number}: {e}",
                exc_info=True
            )

    @staticmethod
    def notify_ticket_assigned(db: Session, ticket, assigned_user):
        """
        Notifica al técnico cuando se le asigna un ticket.
        """
        try:
            from itcj2.sockets.helpdesk import broadcast_ticket_assigned

            fallback_title = f'Ticket #{ticket.ticket_number} asignado a ti'
            fallback_body = f'{ticket.title} - Prioridad: {ticket.priority}'

            context = _build_context(
                ticket=ticket,
                assignee=assigned_user,
            )
            title, body = _render_notification(
                db, 'ticket_assigned', context, fallback_title, fallback_body
            )

            NotificationService.create(
                db=db,
                user_id=assigned_user.id,
                app_name='helpdesk',
                type='TICKET_ASSIGNED',
                title=title,
                body=body,
                data={
                    'ticket_id': ticket.id,
                    'url': f'/help-desk/user/tickets/{ticket.id}',
                    'priority': ticket.priority,
                    'area': ticket.area
                },
                ticket_id=ticket.id
            )

            logger.info(
                f"Notificación TICKET_ASSIGNED enviada a {assigned_user.full_name} para ticket #{ticket.ticket_number}"
            )

            _async_broadcast(broadcast_ticket_assigned(
                ticket.id, assigned_user.id, ticket.area,
                {
                    'ticket_id': ticket.id,
                    'ticket_number': ticket.ticket_number,
                    'title': ticket.title,
                    'assigned_to_id': assigned_user.id,
                    'assigned_to_name': assigned_user.full_name,
                    'area': ticket.area,
                    'priority': ticket.priority
                },
                department_id=ticket.requester_department_id
            ))

        except Exception as e:
            logger.error(f"Error enviando notificación TICKET_ASSIGNED: {e}", exc_info=True)

    @staticmethod
    def notify_ticket_reassigned(db: Session, ticket, new_assigned_user, previous_assigned_user=None):
        """
        Notifica al nuevo técnico y opcionalmente al anterior cuando se reasigna un ticket.
        """
        try:
            from itcj2.sockets.helpdesk import broadcast_ticket_reassigned

            # Notificación para el nuevo técnico asignado
            fallback_title_new = f'Ticket #{ticket.ticket_number} reasignado a ti'
            fallback_body_new = f'{ticket.title} - Prioridad: {ticket.priority}'

            context_new = _build_context(
                ticket=ticket,
                assignee=new_assigned_user,
                previous_assignee=previous_assigned_user,
            )
            title_new, body_new = _render_notification(
                db, 'ticket_reassigned', context_new, fallback_title_new, fallback_body_new
            )

            NotificationService.create(
                db=db,
                user_id=new_assigned_user.id,
                app_name='helpdesk',
                type='TICKET_REASSIGNED',
                title=title_new,
                body=body_new,
                data={
                    'ticket_id': ticket.id,
                    'url': f'/help-desk/user/tickets/{ticket.id}',
                    'priority': ticket.priority
                },
                ticket_id=ticket.id
            )

            # Notificación para el técnico anterior (si existe)
            if previous_assigned_user:
                fallback_title_prev = f'Ticket #{ticket.ticket_number} reasignado'
                fallback_body_prev = f'El ticket fue reasignado a {new_assigned_user.full_name}'

                context_prev = _build_context(
                    ticket=ticket,
                    assignee=new_assigned_user,
                    previous_assignee=previous_assigned_user,
                )
                title_prev, body_prev = _render_notification(
                    db, 'ticket_reassigned', context_prev, fallback_title_prev, fallback_body_prev
                )

                NotificationService.create(
                    db=db,
                    user_id=previous_assigned_user.id,
                    app_name='helpdesk',
                    type='TICKET_REASSIGNED',
                    title=title_prev,
                    body=body_prev,
                    data={
                        'ticket_id': ticket.id,
                        'url': f'/help-desk/user/tickets/{ticket.id}'
                    },
                    ticket_id=ticket.id
                )

            prev_id = previous_assigned_user.id if previous_assigned_user else None
            _async_broadcast(broadcast_ticket_reassigned(
                ticket.id, new_assigned_user.id, prev_id,
                ticket.area,
                {
                    'ticket_id': ticket.id,
                    'ticket_number': ticket.ticket_number,
                    'title': ticket.title,
                    'new_assigned_id': new_assigned_user.id,
                    'new_assigned_name': new_assigned_user.full_name,
                    'prev_assigned_id': prev_id,
                    'prev_assigned_name': previous_assigned_user.full_name if previous_assigned_user else None,
                    'area': ticket.area
                },
                department_id=ticket.requester_department_id
            ))

        except Exception as e:
            logger.error(f"Error enviando notificación TICKET_REASSIGNED: {e}", exc_info=True)

    @staticmethod
    def notify_ticket_self_assigned(db: Session, ticket, technician):
        """
        Notifica al solicitante cuando un técnico toma su ticket del pool del equipo.
        """
        try:
            from itcj2.sockets.helpdesk import broadcast_ticket_self_assigned

            fallback_title = f'Tu ticket #{ticket.ticket_number} fue tomado'
            fallback_body = f'{technician.full_name} comenzará a trabajar en tu ticket'

            context = _build_context(
                ticket=ticket,
                requester=ticket.requester,
                assignee=technician,
            )
            title, body = _render_notification(
                db, 'ticket_self_assigned', context, fallback_title, fallback_body
            )

            NotificationService.create(
                db=db,
                user_id=ticket.requester_id,
                app_name='helpdesk',
                type='TICKET_IN_PROGRESS',
                title=title,
                body=body,
                data={
                    'ticket_id': ticket.id,
                    'url': f'/help-desk/user/tickets/{ticket.id}',
                    'technician': technician.full_name
                },
                ticket_id=ticket.id
            )

            _async_broadcast(broadcast_ticket_self_assigned(
                ticket.id, ticket.area,
                {
                    'ticket_id': ticket.id,
                    'ticket_number': ticket.ticket_number,
                    'title': ticket.title,
                    'technician_id': technician.id,
                    'technician_name': technician.full_name,
                    'area': ticket.area
                }
            ))

        except Exception as e:
            logger.error(f"Error enviando notificación TICKET_SELF_ASSIGNED: {e}", exc_info=True)

    @staticmethod
    def notify_ticket_in_progress(db: Session, ticket):
        """
        Notifica al solicitante cuando el técnico marca el ticket como "en progreso".
        """
        try:
            from itcj2.sockets.helpdesk import broadcast_ticket_status_changed

            technician_name = ticket.assigned_to.full_name if ticket.assigned_to else 'Un técnico'

            fallback_title = f'Trabajando en tu ticket #{ticket.ticket_number}'
            fallback_body = f'{technician_name} comenzó a trabajar en tu solicitud'

            context = _build_context(
                ticket=ticket,
                requester=ticket.requester,
                assignee=ticket.assigned_to,
            )
            title, body = _render_notification(
                db, 'ticket_in_progress', context, fallback_title, fallback_body
            )

            NotificationService.create(
                db=db,
                user_id=ticket.requester_id,
                app_name='helpdesk',
                type='TICKET_IN_PROGRESS',
                title=title,
                body=body,
                data={
                    'ticket_id': ticket.id,
                    'url': f'/help-desk/user/tickets/{ticket.id}'
                },
                ticket_id=ticket.id
            )

            assignee_id = ticket.assigned_to_user_id if hasattr(ticket, 'assigned_to_user_id') else None
            _async_broadcast(broadcast_ticket_status_changed(
                ticket.id, assignee_id, ticket.area,
                {
                    'ticket_id': ticket.id,
                    'ticket_number': ticket.ticket_number,
                    'old_status': 'ASSIGNED',
                    'new_status': 'IN_PROGRESS',
                    'area': ticket.area
                },
                department_id=ticket.requester_department_id
            ))

        except Exception as e:
            logger.error(f"Error enviando notificación TICKET_IN_PROGRESS: {e}", exc_info=True)

    @staticmethod
    def notify_ticket_resolved(db: Session, ticket):
        """
        Notifica al solicitante cuando su ticket fue resuelto.
        """
        try:
            from itcj2.sockets.helpdesk import broadcast_ticket_status_changed

            status_text = {
                'RESOLVED_SUCCESS': 'resuelto exitosamente',
                'RESOLVED_FAILED': 'atendido pero no pudo resolverse completamente'
            }.get(ticket.status, 'resuelto')

            fallback_title = f'Ticket #{ticket.ticket_number} {status_text}'
            fallback_body = f'Por favor califica el servicio recibido'

            context = _build_context(
                ticket=ticket,
                requester=ticket.requester,
            )
            title, body = _render_notification(
                db, 'ticket_resolved', context, fallback_title, fallback_body
            )

            NotificationService.create(
                db=db,
                user_id=ticket.requester_id,
                app_name='helpdesk',
                type='TICKET_RESOLVED',
                title=title,
                body=body,
                data={
                    'ticket_id': ticket.id,
                    'url': f'/help-desk/user/tickets/{ticket.id}',
                    'resolution_status': ticket.status
                },
                ticket_id=ticket.id
            )

            assignee_id = ticket.assigned_to_user_id if hasattr(ticket, 'assigned_to_user_id') else None
            _async_broadcast(broadcast_ticket_status_changed(
                ticket.id, assignee_id, ticket.area,
                {
                    'ticket_id': ticket.id,
                    'ticket_number': ticket.ticket_number,
                    'old_status': 'IN_PROGRESS',
                    'new_status': ticket.status,
                    'area': ticket.area
                },
                department_id=ticket.requester_department_id
            ))

        except Exception as e:
            logger.error(f"Error enviando notificación TICKET_RESOLVED: {e}", exc_info=True)

    @staticmethod
    def notify_ticket_rated(db: Session, ticket, assigned_technician=None):
        """
        Notifica al técnico asignado cuando el usuario califica el ticket.
        """
        try:
            if not assigned_technician and ticket.assigned_to_user_id:
                assigned_technician = db.get(User, ticket.assigned_to_user_id)

            if not assigned_technician:
                return

            avg_rating = (ticket.rating_attention + ticket.rating_speed) / 2 if ticket.rating_attention and ticket.rating_speed else 0

            fallback_title = f'Calificación recibida - Ticket #{ticket.ticket_number}'
            fallback_body = f'Promedio: {avg_rating:.1f}/5 estrellas'

            context = _build_context(
                ticket=ticket,
                assignee=assigned_technician,
            )
            title, body = _render_notification(
                db, 'ticket_rated', context, fallback_title, fallback_body
            )

            NotificationService.create(
                db=db,
                user_id=assigned_technician.id,
                app_name='helpdesk',
                type='TICKET_RATED',
                title=title,
                body=body,
                data={
                    'ticket_id': ticket.id,
                    'url': f'/help-desk/user/tickets/{ticket.id}',
                    'rating_attention': ticket.rating_attention,
                    'rating_speed': ticket.rating_speed,
                    'rating_efficiency': ticket.rating_efficiency
                },
                ticket_id=ticket.id
            )

        except Exception as e:
            logger.error(f"Error enviando notificación TICKET_RATED: {e}", exc_info=True)

    @staticmethod
    def notify_ticket_canceled(db: Session, ticket):
        """
        Notifica al técnico asignado (si existe) cuando el usuario cancela el ticket.
        """
        try:
            from itcj2.sockets.helpdesk import broadcast_ticket_status_changed

            if ticket.assigned_to_user_id:
                fallback_title = f'Ticket #{ticket.ticket_number} cancelado'
                fallback_body = f'El solicitante canceló el ticket: {ticket.title}'

                context = _build_context(
                    ticket=ticket,
                    assignee=ticket.assigned_to,
                )
                title, body = _render_notification(
                    db, 'ticket_canceled', context, fallback_title, fallback_body
                )

                NotificationService.create(
                    db=db,
                    user_id=ticket.assigned_to_user_id,
                    app_name='helpdesk',
                    type='TICKET_CANCELED',
                    title=title,
                    body=body,
                    data={
                        'ticket_id': ticket.id,
                        'url': f'/help-desk/user/tickets/{ticket.id}'
                    },
                    ticket_id=ticket.id
                )

            assignee_id = ticket.assigned_to_user_id if hasattr(ticket, 'assigned_to_user_id') else None
            _async_broadcast(broadcast_ticket_status_changed(
                ticket.id, assignee_id, ticket.area,
                {
                    'ticket_id': ticket.id,
                    'ticket_number': ticket.ticket_number,
                    'old_status': ticket.status,
                    'new_status': 'CANCELED',
                    'area': ticket.area
                },
                department_id=ticket.requester_department_id
            ))

        except Exception as e:
            logger.error(f"Error enviando notificación TICKET_CANCELED: {e}", exc_info=True)

    @staticmethod
    def notify_comment_added(db: Session, ticket, comment, author):
        """
        Notifica a los stakeholders relevantes cuando se agrega un comentario.
        """
        try:
            from itcj2.sockets.helpdesk import broadcast_ticket_comment_added

            recipients = set()

            if ticket.requester_id != author.id:
                recipients.add(ticket.requester_id)

            if ticket.assigned_to_user_id and ticket.assigned_to_user_id != author.id:
                recipients.add(ticket.assigned_to_user_id)

            if not comment.is_internal and hasattr(ticket, 'collaborators'):
                for collab in ticket.collaborators:
                    if collab.user_id != author.id:
                        recipients.add(collab.user_id)

            try:
                if hasattr(ticket, 'comments'):
                    previous_commenters = set()
                    for prev_comment in ticket.comments:
                        if prev_comment.id != comment.id:
                            if comment.is_internal or not prev_comment.is_internal:
                                if prev_comment.author_id and prev_comment.author_id != author.id:
                                    previous_commenters.add(prev_comment.author_id)

                    recipients.update(previous_commenters)

                    if previous_commenters:
                        logger.debug(
                            f"Agregados {len(previous_commenters)} comentadores previos a notificación de ticket #{ticket.ticket_number}"
                        )
            except Exception as e:
                logger.warning(f"Error obteniendo comentadores previos: {e}")

            comment_preview = comment.content[:100] + '...' if len(comment.content) > 100 else comment.content

            fallback_title = f'Nuevo comentario en ticket #{ticket.ticket_number}'
            fallback_body = f'{author.full_name}: {comment_preview}'

            context = _build_context(
                ticket=ticket,
                requester=ticket.requester,
                assignee=ticket.assigned_to,
                commenter=author,
                comment=comment,
            )
            title, body = _render_notification(
                db, 'comment_added', context, fallback_title, fallback_body
            )

            for user_id in recipients:
                NotificationService.create(
                    db=db,
                    user_id=user_id,
                    app_name='helpdesk',
                    type='TICKET_COMMENT',
                    title=title,
                    body=body,
                    data={
                        'ticket_id': ticket.id,
                        'url': f'/help-desk/user/tickets/{ticket.id}#comment-{comment.id}',
                        'comment_id': comment.id,
                        'author': author.full_name
                    },
                    ticket_id=ticket.id
                )

            logger.info(
                f"Notificación TICKET_COMMENT enviada a {len(recipients)} usuarios para ticket #{ticket.ticket_number}"
            )

            preview = comment.content[:100] + '...' if len(comment.content) > 100 else comment.content
            _async_broadcast(broadcast_ticket_comment_added(
                ticket.id,
                {
                    'ticket_id': ticket.id,
                    'ticket_number': ticket.ticket_number,
                    'comment_id': comment.id,
                    'author_id': author.id,
                    'author_name': author.full_name,
                    'is_internal': comment.is_internal,
                    'preview': preview
                }
            ))

        except Exception as e:
            logger.error(f"Error enviando notificación TICKET_COMMENT: {e}", exc_info=True)
