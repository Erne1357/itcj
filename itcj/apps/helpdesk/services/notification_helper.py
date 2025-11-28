"""
Helper de Notificaciones para Helpdesk

Proporciona métodos para crear notificaciones en los diferentes eventos del ciclo de vida de tickets.
Cada método encapsula la lógica de quién debe ser notificado y con qué mensaje.
"""
from typing import Optional
from flask import current_app
from itcj.core.services.notification_service import NotificationService
from itcj.core.extensions import db
from itcj.core.models.user import User
from itcj.core.services.authz_service import _get_users_with_roles_in_app, user_roles_in_app, _get_users_with_position


class HelpdeskNotificationHelper:
    """Helper para crear notificaciones de eventos de helpdesk"""

    @staticmethod
    def notify_ticket_created(ticket):
        """
        Notifica a secretaria/admins cuando se crea un nuevo ticket.

        Args:
            ticket: Instancia de Ticket recién creado
        """
        try:
            # Obtener todos los usuarios con rol 'secretary' o 'admin' en helpdesk
            # Buscar usuarios con esos roles
            recipients = set()

            # Usuarios con roles 'secretary' o 'admin' en la app helpdesk
            #users_by_role = _get_users_with_roles_in_app('helpdesk', ['admin']) or []
            #for u in users_by_role:
            #    if getattr(u, 'id', None):
            #        recipients.add(u.id)

            # Usuarios con la posición 'secretary_comp_center'
            users_by_position = _get_users_with_position(['secretary_comp_center']) or []
            for u in users_by_position:
                if getattr(u, 'id', None):
                    recipients.add(u.id)
                    
            current_app.logger.warning(f"Recipients for TICKET_CREATED: {users_by_position}")

            # Convertir a lista para iterar luego
            recipients = list(recipients)

            # Enviar notificación a cada destinatario
            for user_id in recipients:
                NotificationService.create(
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

            current_app.logger.info(
                f"Notificación TICKET_CREATED enviada a {len(recipients)} usuarios para ticket #{ticket.ticket_number}"
            )

        except Exception as e:
            current_app.logger.error(
                f"Error enviando notificación TICKET_CREATED para ticket #{ticket.ticket_number}: {e}",
                exc_info=True
            )

    @staticmethod
    def notify_ticket_assigned(ticket, assigned_user):
        """
        Notifica al técnico cuando se le asigna un ticket.

        Args:
            ticket: Instancia de Ticket
            assigned_user: Usuario asignado
        """
        try:
            NotificationService.create(
                user_id=assigned_user.id,
                app_name='helpdesk',
                type='TICKET_ASSIGNED',
                title=f'Ticket #{ticket.ticket_number} asignado a ti',
                body=f'{ticket.title} - Prioridad: {ticket.priority}',
                data={
                    'ticket_id': ticket.id,
                    'url': f'/help-desk/technician/tickets/{ticket.id}',
                    'priority': ticket.priority,
                    'area': ticket.area
                },
                ticket_id=ticket.id
            )

            current_app.logger.info(
                f"Notificación TICKET_ASSIGNED enviada a {assigned_user.full_name} para ticket #{ticket.ticket_number}"
            )

        except Exception as e:
            current_app.logger.error(
                f"Error enviando notificación TICKET_ASSIGNED: {e}",
                exc_info=True
            )

    @staticmethod
    def notify_ticket_reassigned(ticket, new_assigned_user, previous_assigned_user=None):
        """
        Notifica al nuevo técnico y opcionalmente al anterior cuando se reasigna un ticket.

        Args:
            ticket: Instancia de Ticket
            new_assigned_user: Nuevo usuario asignado
            previous_assigned_user: Usuario anteriormente asignado (opcional)
        """
        try:
            # Notificar al nuevo técnico
            NotificationService.create(
                user_id=new_assigned_user.id,
                app_name='helpdesk',
                type='TICKET_REASSIGNED',
                title=f'Ticket #{ticket.ticket_number} reasignado a ti',
                body=f'{ticket.title} - Prioridad: {ticket.priority}',
                data={
                    'ticket_id': ticket.id,
                    'url': f'/help-desk/technician/tickets/{ticket.id}',
                    'priority': ticket.priority
                },
                ticket_id=ticket.id
            )

            # Opcionalmente notificar al técnico anterior
            if previous_assigned_user:
                NotificationService.create(
                    user_id=previous_assigned_user.id,
                    app_name='helpdesk',
                    type='TICKET_REASSIGNED',
                    title=f'Ticket #{ticket.ticket_number} reasignado',
                    body=f'El ticket fue reasignado a {new_assigned_user.full_name}',
                    data={
                        'ticket_id': ticket.id,
                        'url': f'/help-desk/technician/tickets/{ticket.id}'
                    },
                    ticket_id=ticket.id
                )

        except Exception as e:
            current_app.logger.error(
                f"Error enviando notificación TICKET_REASSIGNED: {e}",
                exc_info=True
            )

    @staticmethod
    def notify_ticket_self_assigned(ticket, technician):
        """
        Notifica al solicitante cuando un técnico toma su ticket del pool del equipo.

        Args:
            ticket: Instancia de Ticket
            technician: Usuario técnico que tomó el ticket
        """
        try:
            NotificationService.create(
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

        except Exception as e:
            current_app.logger.error(
                f"Error enviando notificación TICKET_SELF_ASSIGNED: {e}",
                exc_info=True
            )

    @staticmethod
    def notify_ticket_in_progress(ticket):
        """
        Notifica al solicitante cuando el técnico marca el ticket como "en progreso".

        Args:
            ticket: Instancia de Ticket
        """
        try:
            technician_name = ticket.assigned_to.full_name if ticket.assigned_to else 'Un técnico'

            NotificationService.create(
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

        except Exception as e:
            current_app.logger.error(
                f"Error enviando notificación TICKET_IN_PROGRESS: {e}",
                exc_info=True
            )

    @staticmethod
    def notify_ticket_resolved(ticket):
        """
        Notifica al solicitante cuando su ticket fue resuelto.

        Args:
            ticket: Instancia de Ticket
        """
        try:
            status_text = {
                'RESOLVED_SUCCESS': 'resuelto exitosamente',
                'RESOLVED_FAILED': 'atendido pero no pudo resolverse completamente'
            }.get(ticket.status, 'resuelto')

            NotificationService.create(
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

        except Exception as e:
            current_app.logger.error(
                f"Error enviando notificación TICKET_RESOLVED: {e}",
                exc_info=True
            )

    @staticmethod
    def notify_ticket_rated(ticket, assigned_technician=None):
        """
        Notifica al técnico asignado cuando el usuario califica el ticket (opcional).

        Args:
            ticket: Instancia de Ticket
            assigned_technician: Usuario técnico (opcional)
        """
        try:
            if not assigned_technician and ticket.assigned_to_user_id:
                assigned_technician = db.session.query(User).get(ticket.assigned_to_user_id)

            if not assigned_technician:
                return  # No hay a quién notificar

            # Calcular promedio simple (atención + rapidez) / 2
            avg_rating = (ticket.rating_attention + ticket.rating_speed) / 2 if ticket.rating_attention and ticket.rating_speed else 0

            NotificationService.create(
                user_id=assigned_technician.id,
                app_name='helpdesk',
                type='TICKET_RATED',
                title=f'Calificación recibida - Ticket #{ticket.ticket_number}',
                body=f'Promedio: {avg_rating:.1f}/5 estrellas',
                data={
                    'ticket_id': ticket.id,
                    'url': f'/help-desk/technician/tickets/{ticket.id}',
                    'rating_attention': ticket.rating_attention,
                    'rating_speed': ticket.rating_speed,
                    'rating_efficiency': ticket.rating_efficiency
                },
                ticket_id=ticket.id
            )

        except Exception as e:
            current_app.logger.error(
                f"Error enviando notificación TICKET_RATED: {e}",
                exc_info=True
            )

    @staticmethod
    def notify_ticket_canceled(ticket):
        """
        Notifica al técnico asignado (si existe) cuando el usuario cancela el ticket.

        Args:
            ticket: Instancia de Ticket
        """
        try:
            if ticket.assigned_to_user_id:
                NotificationService.create(
                    user_id=ticket.assigned_to_user_id,
                    app_name='helpdesk',
                    type='TICKET_CANCELED',
                    title=f'Ticket #{ticket.ticket_number} cancelado',
                    body=f'El solicitante canceló el ticket: {ticket.title}',
                    data={
                        'ticket_id': ticket.id,
                        'url': f'/help-desk/technician/tickets/{ticket.id}'
                    },
                    ticket_id=ticket.id
                )

        except Exception as e:
            current_app.logger.error(
                f"Error enviando notificación TICKET_CANCELED: {e}",
                exc_info=True
            )

    @staticmethod
    def notify_comment_added(ticket, comment, author):
        """
        Notifica a los stakeholders relevantes cuando se agrega un comentario.

        Notifica a:
        - Solicitante (si el comentario no es de él)
        - Técnico asignado (si el comentario no es de él)
        - Colaboradores (si los hay y el comentario no es privado)

        Args:
            ticket: Instancia de Ticket
            comment: Instancia de Comment
            author: Usuario que escribió el comentario
        """
        try:
            recipients = set()

            # Agregar solicitante (si no es el autor)
            if ticket.requester_id != author.id:
                recipients.add(ticket.requester_id)

            # Agregar técnico asignado (si existe y no es el autor)
            if ticket.assigned_to_user_id and ticket.assigned_to_user_id != author.id:
                recipients.add(ticket.assigned_to_user_id)

            # Agregar colaboradores (si el comentario no es interno)
            if not comment.is_internal and hasattr(ticket, 'collaborators'):
                for collab in ticket.collaborators:
                    if collab.user_id != author.id:
                        recipients.add(collab.user_id)

            # Enviar notificaciones
            for user_id in recipients:
                NotificationService.create(
                    user_id=user_id,
                    app_name='helpdesk',
                    type='TICKET_COMMENT',
                    title=f'Nuevo comentario en ticket #{ticket.ticket_number}',
                    body=f'{author.full_name}: {comment.text[:100]}...' if len(comment.text) > 100 else f'{author.full_name}: {comment.text}',
                    data={
                        'ticket_id': ticket.id,
                        'url': f'/help-desk/user/tickets/{ticket.id}#comment-{comment.id}',
                        'comment_id': comment.id,
                        'author': author.full_name
                    },
                    ticket_id=ticket.id
                )

            current_app.logger.info(
                f"Notificación TICKET_COMMENT enviada a {len(recipients)} usuarios para ticket #{ticket.ticket_number}"
            )

        except Exception as e:
            current_app.logger.error(
                f"Error enviando notificación TICKET_COMMENT: {e}",
                exc_info=True
            )
