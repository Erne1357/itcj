"""
Helper de Notificaciones para la app de Mantenimiento.

Notifica a los actores relevantes en cada evento del ciclo de vida
de los tickets. Sin WebSocket por ahora — solo notificaciones en BD.
"""
import logging

from sqlalchemy.orm import Session

from itcj2.core.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

_BASE_URL = '/maintenance/tickets'


class MaintNotificationHelper:

    @staticmethod
    def notify_ticket_created(db: Session, ticket) -> None:
        """Notifica a dispatchers cuando se crea un nuevo ticket."""
        try:
            from itcj2.core.models.user_app_role import UserAppRole
            from itcj2.core.models.app import App
            from itcj2.core.models.role import Role

            app = db.query(App).filter_by(key='maint').first()
            if not app:
                return

            dispatcher_role = db.query(Role).filter_by(name='dispatcher').first()
            admin_role = db.query(Role).filter_by(name='admin').first()
            role_ids = {r.id for r in [dispatcher_role, admin_role] if r}

            if not role_ids:
                return

            assignments = db.query(UserAppRole).filter(
                UserAppRole.app_id == app.id,
                UserAppRole.role_id.in_(role_ids),
            ).all()

            requester_name = ticket.requester.full_name if ticket.requester else 'Desconocido'
            recipients = {a.user_id for a in assignments}
            recipients.discard(ticket.requester_id)

            for user_id in recipients:
                NotificationService.create(
                    db=db,
                    user_id=user_id,
                    app_name='maint',
                    type='TICKET_CREATED',
                    title=f'Nueva solicitud #{ticket.ticket_number}',
                    body=f'{ticket.category.name if ticket.category else ""} — {ticket.title[:80]}',
                    data={
                        'ticket_id': ticket.id,
                        'url': f'{_BASE_URL}/{ticket.id}',
                        'priority': ticket.priority,
                        'requester': requester_name,
                    },
                    ticket_id=ticket.id,
                )

            logger.info(
                f"[maint] TICKET_CREATED enviado a {len(recipients)} usuarios para #{ticket.ticket_number}"
            )
        except Exception as exc:
            logger.error(f"[maint] Error en notify_ticket_created: {exc}", exc_info=True)

    @staticmethod
    def notify_technician_assigned(db: Session, ticket, technician_id: int) -> None:
        """Notifica al técnico cuando se le asigna un ticket."""
        try:
            from itcj2.core.models.user import User
            technician = db.get(User, technician_id)
            if not technician:
                return

            NotificationService.create(
                db=db,
                user_id=technician_id,
                app_name='maint',
                type='TICKET_ASSIGNED',
                title=f'Ticket #{ticket.ticket_number} asignado a ti',
                body=f'{ticket.title[:100]}',
                data={
                    'ticket_id': ticket.id,
                    'url': f'{_BASE_URL}/{ticket.id}',
                    'priority': ticket.priority,
                    'category': ticket.category.name if ticket.category else '',
                },
                ticket_id=ticket.id,
            )

            logger.info(f"[maint] TICKET_ASSIGNED → {technician.full_name} para #{ticket.ticket_number}")
        except Exception as exc:
            logger.error(f"[maint] Error en notify_technician_assigned: {exc}", exc_info=True)

    @staticmethod
    def notify_ticket_resolved(db: Session, ticket) -> None:
        """Notifica al solicitante que su ticket fue resuelto y pide calificación."""
        try:
            status_text = {
                'RESOLVED_SUCCESS': 'resuelto exitosamente',
                'RESOLVED_FAILED': 'atendido (sin resolución completa)',
            }.get(ticket.status, 'resuelto')

            NotificationService.create(
                db=db,
                user_id=ticket.requester_id,
                app_name='maint',
                type='TICKET_RESOLVED',
                title=f'Tu solicitud #{ticket.ticket_number} fue {status_text}',
                body='Por favor califica el servicio recibido.',
                data={
                    'ticket_id': ticket.id,
                    'url': f'{_BASE_URL}/{ticket.id}',
                    'resolution_status': ticket.status,
                },
                ticket_id=ticket.id,
            )

            logger.info(f"[maint] TICKET_RESOLVED → requester para #{ticket.ticket_number}")
        except Exception as exc:
            logger.error(f"[maint] Error en notify_ticket_resolved: {exc}", exc_info=True)

    @staticmethod
    def notify_ticket_canceled(db: Session, ticket) -> None:
        """Notifica a los técnicos activos cuando se cancela el ticket."""
        try:
            active_tech_ids = [t.user_id for t in ticket.active_technicians]
            for tech_id in active_tech_ids:
                NotificationService.create(
                    db=db,
                    user_id=tech_id,
                    app_name='maint',
                    type='TICKET_CANCELED',
                    title=f'Ticket #{ticket.ticket_number} cancelado',
                    body=ticket.cancel_reason or ticket.title[:80],
                    data={
                        'ticket_id': ticket.id,
                        'url': f'{_BASE_URL}/{ticket.id}',
                    },
                    ticket_id=ticket.id,
                )
        except Exception as exc:
            logger.error(f"[maint] Error en notify_ticket_canceled: {exc}", exc_info=True)

    @staticmethod
    def notify_comment_added(db: Session, ticket, comment, author_id: int) -> None:
        """Notifica a los involucrados cuando se agrega un comentario."""
        try:
            from itcj2.core.models.user import User
            author = db.get(User, author_id)
            author_name = author.full_name if author else 'Alguien'

            recipients = {ticket.requester_id}
            for t in ticket.active_technicians:
                recipients.add(t.user_id)
            recipients.discard(author_id)

            preview = comment.content[:100] + ('...' if len(comment.content) > 100 else '')

            for user_id in recipients:
                # Los comentarios internos solo llegan a técnicos/dispatchers
                if comment.is_internal and user_id == ticket.requester_id:
                    continue
                NotificationService.create(
                    db=db,
                    user_id=user_id,
                    app_name='maint',
                    type='TICKET_COMMENT',
                    title=f'Nuevo comentario en #{ticket.ticket_number}',
                    body=f'{author_name}: {preview}',
                    data={
                        'ticket_id': ticket.id,
                        'url': f'{_BASE_URL}/{ticket.id}',
                    },
                    ticket_id=ticket.id,
                )
        except Exception as exc:
            logger.error(f"[maint] Error en notify_comment_added: {exc}", exc_info=True)
