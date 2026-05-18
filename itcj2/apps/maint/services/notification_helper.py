"""
Helper de Notificaciones para la app de Mantenimiento.

Notifica a los actores relevantes en cada evento del ciclo de vida de los tickets.
Incluye broadcasts WebSocket via itcj2.sockets.maint para actualizaciones en tiempo real.

== Plantillas desde BD ==
render_notification() intenta resolver title/subject/body desde MaintNotificationTemplate
(via catalog_cache). Si la plantilla está inactiva, ausente, o el render falla por
cualquier motivo, usa los strings hardcoded pasados como fallback. Esto garantiza que
el flujo de tickets NUNCA se rompe por un error de plantilla.
"""
import logging
from typing import Optional

from jinja2 import Environment, ChainableUndefined
from sqlalchemy.orm import Session

from itcj2.core.services.notification_service import NotificationService
from itcj2.utils import async_broadcast as _async_broadcast

logger = logging.getLogger(__name__)

_BASE_URL = '/maint/tickets'


# ==================== RENDER DE PLANTILLAS ====================

def render_notification(
    db,
    code: str,
    context: dict,
    *,
    fallback_title: Optional[str] = None,
    fallback_subject: Optional[str] = None,
    fallback_body: str,
) -> dict:
    """
    Intenta renderizar title/subject/body desde la plantilla BD con el code indicado.

    Flujo:
    1. Busca la plantilla en cache (get_notification_template) — solo retorna si activa.
    2. Renderiza title_template, subject_template y body_template con Jinja2
       usando ChainableUndefined (variables faltantes → cadena vacía, sin lanzar).
    3. Ante CUALQUIER excepción en cualquier paso → devuelve los fallbacks.

    Retorna siempre un dict con claves 'title', 'subject', 'body'. Nunca lanza.
    """
    _fallback = {
        "title": fallback_title,
        "subject": fallback_subject,
        "body": fallback_body,
    }
    try:
        from itcj2.apps.maint.utils.catalog_cache import get_notification_template

        tpl = get_notification_template(code)
        if tpl is None:
            # Plantilla inactiva, ausente o error de BD → fallback silencioso
            return _fallback

        env = Environment(undefined=ChainableUndefined, autoescape=False)

        def _render_field(template_str: Optional[str], default: Optional[str]) -> Optional[str]:
            if not template_str:
                return default
            try:
                return env.from_string(template_str).render(**context)
            except Exception as render_exc:
                logger.warning(
                    "[maint] render_notification: error renderizando campo de plantilla '%s': %s",
                    code, render_exc,
                )
                return default

        return {
            "title": _render_field(tpl.get("title_template"), fallback_title),
            "subject": _render_field(tpl.get("subject_template"), fallback_subject),
            "body": _render_field(tpl.get("body_template"), fallback_body),
        }

    except Exception as exc:
        logger.warning(
            "[maint] render_notification: error inesperado al renderizar plantilla '%s': %s",
            code, exc,
        )
        return _fallback


# ==================== HELPER DE NOTIFICACIONES ====================

class MaintNotificationHelper:

    @staticmethod
    def notify_ticket_created(db: Session, ticket) -> None:
        """Notifica a dispatchers cuando se crea un nuevo ticket."""
        try:
            from itcj2.core.models.user_app_role import UserAppRole
            from itcj2.core.models.app import App
            from itcj2.core.models.role import Role
            from itcj2.sockets.maint import broadcast_ticket_created

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

            context = {
                'ticket': ticket,
                'requester': ticket.requester,
                'requester_name': requester_name,
            }
            rendered = render_notification(
                db=db,
                code='ticket_created',
                context=context,
                fallback_title=f'Nueva solicitud #{ticket.ticket_number}',
                fallback_body=f'{ticket.category.name if ticket.category else ""} — {ticket.title[:80]}',
            )

            for user_id in recipients:
                NotificationService.create(
                    db=db,
                    user_id=user_id,
                    app_name='maint',
                    type='TICKET_CREATED',
                    title=rendered['title'],
                    body=rendered['body'],
                    data={
                        'ticket_id': ticket.id,
                        'url': f'{_BASE_URL}/{ticket.id}',
                        'priority': ticket.priority,
                        'requester': requester_name,
                    },
                )

            logger.info(
                f"[maint] TICKET_CREATED enviado a {len(recipients)} usuarios para #{ticket.ticket_number}"
            )

            department_id = getattr(ticket, 'requester_department_id', None)
            _async_broadcast(broadcast_ticket_created({
                'ticket_id': ticket.id,
                'ticket_number': ticket.ticket_number,
                'title': ticket.title,
                'status': ticket.status,
                'priority': ticket.priority,
                'category': ticket.category.name if ticket.category else None,
                'requester': requester_name,
                'department_id': department_id,
            }))

        except Exception as exc:
            logger.error(f"[maint] Error en notify_ticket_created: {exc}", exc_info=True)

    @staticmethod
    def notify_technician_assigned(db: Session, ticket, technician_id: int) -> None:
        """Notifica al técnico cuando se le asigna un ticket."""
        try:
            from itcj2.core.models.user import User
            from itcj2.sockets.maint import broadcast_ticket_assigned

            technician = db.get(User, technician_id)
            if not technician:
                return

            context = {
                'ticket': ticket,
                'technician': technician,
            }
            rendered = render_notification(
                db=db,
                code='ticket_assigned',
                context=context,
                fallback_title=f'Ticket #{ticket.ticket_number} asignado a ti',
                fallback_body=f'{ticket.title[:100]}',
            )

            NotificationService.create(
                db=db,
                user_id=technician_id,
                app_name='maint',
                type='TICKET_ASSIGNED',
                title=rendered['title'],
                body=rendered['body'],
                data={
                    'ticket_id': ticket.id,
                    'url': f'{_BASE_URL}/{ticket.id}',
                    'priority': ticket.priority,
                    'category': ticket.category.name if ticket.category else '',
                },
            )

            logger.info(f"[maint] TICKET_ASSIGNED → {technician.full_name} para #{ticket.ticket_number}")

            department_id = getattr(ticket, 'requester_department_id', None)
            active_tech_ids = [t.user_id for t in ticket.active_technicians]
            _async_broadcast(broadcast_ticket_assigned(
                ticket.id,
                active_tech_ids,
                {
                    'ticket_id': ticket.id,
                    'ticket_number': ticket.ticket_number,
                    'title': ticket.title,
                    'status': ticket.status,
                    'priority': ticket.priority,
                    'assigned_to_id': technician_id,
                    'assigned_to_name': technician.full_name,
                },
                department_id=department_id,
            ))

        except Exception as exc:
            logger.error(f"[maint] Error en notify_technician_assigned: {exc}", exc_info=True)

    @staticmethod
    def notify_ticket_in_progress(db: Session, ticket) -> None:
        """Notifica al solicitante que el técnico comenzó a trabajar en su ticket."""
        try:
            from itcj2.sockets.maint import broadcast_ticket_status_changed

            active_tech_ids = [t.user_id for t in ticket.active_technicians]
            tech_name = 'Un técnico'
            tech = None
            if active_tech_ids:
                from itcj2.core.models.user import User
                tech = db.get(User, active_tech_ids[0])
                tech_name = tech.full_name if tech else tech_name

            context = {
                'ticket': ticket,
                'technician': tech,
                'tech_name': tech_name,
            }
            rendered = render_notification(
                db=db,
                code='ticket_in_progress',
                context=context,
                fallback_title=f'Trabajando en tu solicitud #{ticket.ticket_number}',
                fallback_body=f'{tech_name} comenzó a atender tu solicitud',
            )

            NotificationService.create(
                db=db,
                user_id=ticket.requester_id,
                app_name='maint',
                type='TICKET_IN_PROGRESS',
                title=rendered['title'],
                body=rendered['body'],
                data={
                    'ticket_id': ticket.id,
                    'url': f'{_BASE_URL}/{ticket.id}',
                },
            )

            logger.info(f"[maint] TICKET_IN_PROGRESS → requester para #{ticket.ticket_number}")

            department_id = getattr(ticket, 'requester_department_id', None)
            _async_broadcast(broadcast_ticket_status_changed(
                ticket.id,
                active_tech_ids,
                {
                    'ticket_id': ticket.id,
                    'ticket_number': ticket.ticket_number,
                    'title': ticket.title,
                    'old_status': 'ASSIGNED',
                    'new_status': 'IN_PROGRESS',
                    'priority': ticket.priority,
                },
                department_id=department_id,
            ))

        except Exception as exc:
            logger.error(f"[maint] Error en notify_ticket_in_progress: {exc}", exc_info=True)

    @staticmethod
    def notify_ticket_resolved(db: Session, ticket) -> None:
        """Notifica al solicitante que su ticket fue resuelto y pide calificación."""
        try:
            from itcj2.sockets.maint import broadcast_ticket_resolved

            status_text = {
                'RESOLVED_SUCCESS': 'resuelto exitosamente',
                'RESOLVED_FAILED': 'atendido (sin resolución completa)',
            }.get(ticket.status, 'resuelto')

            context = {
                'ticket': ticket,
                'requester': ticket.requester,
                'status_text': status_text,
            }
            rendered = render_notification(
                db=db,
                code='ticket_resolved',
                context=context,
                fallback_title=f'Tu solicitud #{ticket.ticket_number} fue {status_text}',
                fallback_body='Por favor califica el servicio recibido.',
            )

            NotificationService.create(
                db=db,
                user_id=ticket.requester_id,
                app_name='maint',
                type='TICKET_RESOLVED',
                title=rendered['title'],
                body=rendered['body'],
                data={
                    'ticket_id': ticket.id,
                    'url': f'{_BASE_URL}/{ticket.id}#resolution',
                    'resolution_status': ticket.status,
                },
            )

            logger.info(f"[maint] TICKET_RESOLVED → requester para #{ticket.ticket_number}")

            department_id = getattr(ticket, 'requester_department_id', None)
            resolved_by_id = getattr(ticket, 'resolved_by_id', None)
            _async_broadcast(broadcast_ticket_resolved(
                ticket.id,
                ticket.requester_id,
                {
                    'ticket_id': ticket.id,
                    'ticket_number': ticket.ticket_number,
                    'title': ticket.title,
                    'status': ticket.status,
                    'priority': ticket.priority,
                    'resolved_by_id': resolved_by_id,
                },
                department_id=department_id,
            ))

        except Exception as exc:
            logger.error(f"[maint] Error en notify_ticket_resolved: {exc}", exc_info=True)

    @staticmethod
    def notify_ticket_canceled(db: Session, ticket) -> None:
        """Notifica a los técnicos activos cuando se cancela el ticket."""
        try:
            from itcj2.sockets.maint import broadcast_ticket_canceled

            active_tech_ids = [t.user_id for t in ticket.active_technicians]

            context = {
                'ticket': ticket,
                'cancel_reason': ticket.cancel_reason,
            }
            rendered = render_notification(
                db=db,
                code='ticket_canceled',
                context=context,
                fallback_title=f'Ticket #{ticket.ticket_number} cancelado',
                fallback_body=ticket.cancel_reason or ticket.title[:80],
            )

            for tech_id in active_tech_ids:
                NotificationService.create(
                    db=db,
                    user_id=tech_id,
                    app_name='maint',
                    type='TICKET_CANCELED',
                    title=rendered['title'],
                    body=rendered['body'],
                    data={
                        'ticket_id': ticket.id,
                        'url': f'{_BASE_URL}/{ticket.id}',
                    },
                )

            logger.info(
                f"[maint] TICKET_CANCELED enviado a {len(active_tech_ids)} técnicos para #{ticket.ticket_number}"
            )

            department_id = getattr(ticket, 'requester_department_id', None)
            _async_broadcast(broadcast_ticket_canceled(
                ticket.id,
                active_tech_ids,
                {
                    'ticket_id': ticket.id,
                    'ticket_number': ticket.ticket_number,
                    'title': ticket.title,
                    'status': 'CANCELED',
                    'priority': ticket.priority,
                    'cancel_reason': getattr(ticket, 'cancel_reason', None),
                },
                department_id=department_id,
            ))

        except Exception as exc:
            logger.error(f"[maint] Error en notify_ticket_canceled: {exc}", exc_info=True)

    @staticmethod
    def notify_ticket_rated(db: Session, ticket) -> None:
        """Notifica a los técnicos activos y al técnico que resolvió cuando se califica un ticket."""
        try:
            from itcj2.sockets.maint import broadcast_ticket_rated

            active_tech_ids = [t.user_id for t in ticket.active_technicians]
            resolved_by_id = getattr(ticket, 'resolved_by_id', None)

            recipient_ids: set = set(active_tech_ids)
            if resolved_by_id:
                recipient_ids.add(resolved_by_id)

            avg_rating = None
            r_attention = getattr(ticket, 'rating_attention', None)
            r_speed = getattr(ticket, 'rating_speed', None)
            if r_attention and r_speed:
                avg_rating = round((r_attention + r_speed) / 2, 1)

            context = {
                'ticket': ticket,
                'avg_rating': avg_rating,
                'rating_attention': r_attention,
                'rating_speed': r_speed,
            }
            rendered = render_notification(
                db=db,
                code='ticket_rated',
                context=context,
                fallback_title=f'Calificación recibida — #{ticket.ticket_number}',
                fallback_body=f'Promedio: {avg_rating}/5' if avg_rating else 'Nueva calificación recibida',
            )

            for tech_id in recipient_ids:
                NotificationService.create(
                    db=db,
                    user_id=tech_id,
                    app_name='maint',
                    type='TICKET_RATED',
                    title=rendered['title'],
                    body=rendered['body'],
                    data={
                        'ticket_id': ticket.id,
                        'url': f'{_BASE_URL}/{ticket.id}#resolution',
                        'rating_attention': r_attention,
                        'rating_speed': r_speed,
                        'rating_efficiency': getattr(ticket, 'rating_efficiency', None),
                    },
                )

            logger.info(
                f"[maint] TICKET_RATED enviado a {len(recipient_ids)} técnicos para #{ticket.ticket_number}"
            )

            _async_broadcast(broadcast_ticket_rated(
                ticket.id,
                list(recipient_ids),
                {
                    'ticket_id': ticket.id,
                    'ticket_number': ticket.ticket_number,
                    'rating_attention': r_attention,
                    'rating_speed': r_speed,
                    'rating_efficiency': getattr(ticket, 'rating_efficiency', None),
                    'avg_rating': avg_rating,
                },
            ))

        except Exception as exc:
            logger.error(f"[maint] Error en notify_ticket_rated: {exc}", exc_info=True)

    @staticmethod
    def notify_comment_added(db: Session, ticket, comment, author_id: int) -> None:
        """Notifica a los involucrados cuando se agrega un comentario."""
        try:
            from itcj2.core.models.user import User
            from itcj2.sockets.maint import broadcast_ticket_comment_added

            author = db.get(User, author_id)
            author_name = author.full_name if author else 'Alguien'

            recipients = {ticket.requester_id}
            for t in ticket.active_technicians:
                recipients.add(t.user_id)
            recipients.discard(author_id)

            preview = comment.content[:100] + ('...' if len(comment.content) > 100 else '')

            context = {
                'ticket': ticket,
                'comment': comment,
                'author': author,
                'author_name': author_name,
                'preview': preview,
            }
            rendered = render_notification(
                db=db,
                code='ticket_comment',
                context=context,
                fallback_title=f'Nuevo comentario en #{ticket.ticket_number}',
                fallback_body=f'{author_name}: {preview}',
            )

            for user_id in recipients:
                # Los comentarios internos solo llegan a técnicos/dispatchers
                if comment.is_internal and user_id == ticket.requester_id:
                    continue
                NotificationService.create(
                    db=db,
                    user_id=user_id,
                    app_name='maint',
                    type='TICKET_COMMENT',
                    title=rendered['title'],
                    body=rendered['body'],
                    data={
                        'ticket_id': ticket.id,
                        'url': f'{_BASE_URL}/{ticket.id}#comments',
                    },
                )

            logger.info(
                f"[maint] TICKET_COMMENT enviado a {len(recipients)} usuarios para #{ticket.ticket_number}"
            )

            _async_broadcast(broadcast_ticket_comment_added(
                ticket.id,
                {
                    'ticket_id': ticket.id,
                    'ticket_number': ticket.ticket_number,
                    'comment_id': comment.id,
                    'author_id': author_id,
                    'author_name': author_name,
                    'is_internal': comment.is_internal,
                    'preview': preview,
                },
            ))

        except Exception as exc:
            logger.error(f"[maint] Error en notify_comment_added: {exc}", exc_info=True)
