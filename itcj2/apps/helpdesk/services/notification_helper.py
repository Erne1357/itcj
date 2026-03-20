"""
Helper de Notificaciones para Helpdesk

Proporciona métodos para crear notificaciones en los diferentes eventos del ciclo de vida de tickets.
Incluye broadcasts WebSocket para actualizaciones en tiempo real.
"""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from itcj2.core.services.notification_service import NotificationService
from itcj2.core.models.user import User
from itcj2.core.services.authz_service import _get_users_with_position
from itcj2.utils import async_broadcast as _async_broadcast

logger = logging.getLogger(__name__)


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

            for user_id in recipients:
                NotificationService.create(
                    db=db,
                    user_id=user_id,
                    app_name='helpdesk',
                    type='TICKET_CREATED',
                    title=f'Nuevo ticket #{ticket.ticket_number}',
                    body=f'{ticket.title} - Prioridad: {ticket.priority}',
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

            NotificationService.create(
                db=db,
                user_id=assigned_user.id,
                app_name='helpdesk',
                type='TICKET_ASSIGNED',
                title=f'Ticket #{ticket.ticket_number} asignado a ti',
                body=f'{ticket.title} - Prioridad: {ticket.priority}',
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

            NotificationService.create(
                db=db,
                user_id=new_assigned_user.id,
                app_name='helpdesk',
                type='TICKET_REASSIGNED',
                title=f'Ticket #{ticket.ticket_number} reasignado a ti',
                body=f'{ticket.title} - Prioridad: {ticket.priority}',
                data={
                    'ticket_id': ticket.id,
                    'url': f'/help-desk/user/tickets/{ticket.id}',
                    'priority': ticket.priority
                },
                ticket_id=ticket.id
            )

            if previous_assigned_user:
                NotificationService.create(
                    db=db,
                    user_id=previous_assigned_user.id,
                    app_name='helpdesk',
                    type='TICKET_REASSIGNED',
                    title=f'Ticket #{ticket.ticket_number} reasignado',
                    body=f'El ticket fue reasignado a {new_assigned_user.full_name}',
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

            NotificationService.create(
                db=db,
                user_id=ticket.requester_id,
                app_name='helpdesk',
                type='TICKET_IN_PROGRESS',
                title=f'Tu ticket #{ticket.ticket_number} fue tomado',
                body=f'{technician.full_name} comenzará a trabajar en tu ticket',
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

            NotificationService.create(
                db=db,
                user_id=ticket.requester_id,
                app_name='helpdesk',
                type='TICKET_IN_PROGRESS',
                title=f'Trabajando en tu ticket #{ticket.ticket_number}',
                body=f'{technician_name} comenzó a trabajar en tu solicitud',
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

            NotificationService.create(
                db=db,
                user_id=ticket.requester_id,
                app_name='helpdesk',
                type='TICKET_RESOLVED',
                title=f'Ticket #{ticket.ticket_number} {status_text}',
                body=f'Por favor califica el servicio recibido',
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

            NotificationService.create(
                db=db,
                user_id=assigned_technician.id,
                app_name='helpdesk',
                type='TICKET_RATED',
                title=f'Calificación recibida - Ticket #{ticket.ticket_number}',
                body=f'Promedio: {avg_rating:.1f}/5 estrellas',
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
                NotificationService.create(
                    db=db,
                    user_id=ticket.assigned_to_user_id,
                    app_name='helpdesk',
                    type='TICKET_CANCELED',
                    title=f'Ticket #{ticket.ticket_number} cancelado',
                    body=f'El solicitante canceló el ticket: {ticket.title}',
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

            for user_id in recipients:
                NotificationService.create(
                    db=db,
                    user_id=user_id,
                    app_name='helpdesk',
                    type='TICKET_COMMENT',
                    title=f'Nuevo comentario en ticket #{ticket.ticket_number}',
                    body=f'{author.full_name}: {comment.content[:100]}...' if len(comment.content) > 100 else f'{author.full_name}: {comment.content}',
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
