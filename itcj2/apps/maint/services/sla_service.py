"""
Servicio de alertas SLA para tickets de mantenimiento vencidos.

Ciclo de vida (poll-driven, no event-driven):
  1. find_overdue_tickets  — consulta tickets abiertos cuyo due_at ya pasó
                             y que aún no han sido alertados (o fueron alertados
                             hace >24 h, para re-alertar diariamente).
  2. notify_overdue        — emite notificaciones TICKET_OVERDUE a técnicos
                             activos + dispatchers/admins y hace broadcast WS.
  3. run_overdue_check     — orquestador: llama a los dos anteriores en un pase
                             único, commit final único.

Este servicio se invoca desde un cron script externo (itcj2/scripts/maint_sla_check.py).
Deliberadamente está separado de MaintNotificationHelper porque ese helper es
event-driven; el SLA check es poll-driven.
"""
import logging
from datetime import timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from itcj2.apps.maint.utils.timezone_utils import now_local

logger = logging.getLogger(__name__)

_BASE_URL = '/maint/tickets'

# Estados considerados "abiertos" para la alerta SLA
_OPEN_STATUSES = ('PENDING', 'ASSIGNED', 'IN_PROGRESS')


def find_overdue_tickets(db: Session) -> list:
    """
    Devuelve tickets abiertos cuyo due_at ya pasó y que:
      - nunca han sido alertados (sla_alert_sent_at IS NULL), o
      - la última alerta fue hace más de 24 h (re-alerta diaria hasta que se resuelvan).
    Ordenados por due_at ascendente (más urgentes primero).
    """
    from itcj2.apps.maint.models.ticket import MaintTicket

    now = now_local()
    cutoff_realert = now - timedelta(hours=24)

    return (
        db.query(MaintTicket)
        .filter(
            MaintTicket.status.in_(_OPEN_STATUSES),
            MaintTicket.due_at.isnot(None),
            MaintTicket.due_at < now,
            or_(
                MaintTicket.sla_alert_sent_at.is_(None),
                MaintTicket.sla_alert_sent_at < cutoff_realert,
            ),
        )
        .order_by(MaintTicket.due_at.asc())
        .all()
    )


def notify_overdue(db: Session, ticket) -> int:
    """
    Envía la notificación TICKET_OVERDUE a:
      - Técnicos activos asignados al ticket (unassigned_at IS NULL).
      - Usuarios con rol 'dispatcher' o 'admin' en la app 'maint'.

    Tras crear las notificaciones, hace broadcast WS con is_overdue=True y
    sla_overdue=True para que la UI actualice el badge en tiempo real sin
    cambiar el status real del ticket.

    Actualiza ticket.sla_alert_sent_at = now_local() (el commit lo hace el
    orquestador run_overdue_check para un commit único por pase).

    Devuelve el número de notificaciones creadas.
    """
    from itcj2.core.models.user_app_role import UserAppRole
    from itcj2.core.models.app import App
    from itcj2.core.models.role import Role
    from itcj2.core.services.notification_service import NotificationService
    from itcj2.utils import async_broadcast as _async_broadcast

    now = now_local()

    # ── Técnicos activos del ticket ────────────────────────────────────────
    active_tech_ids = {
        t.user_id
        for t in ticket.technicians
        if t.unassigned_at is None
    }

    # ── Dispatchers y admins en la app maint ──────────────────────────────
    app = db.query(App).filter_by(key='maint').first()
    dispatcher_admin_ids: set = set()
    if app:
        dispatcher_role = db.query(Role).filter_by(name='dispatcher').first()
        admin_role = db.query(Role).filter_by(name='admin').first()
        role_ids = {r.id for r in [dispatcher_role, admin_role] if r}
        if role_ids:
            rows = db.query(UserAppRole).filter(
                UserAppRole.app_id == app.id,
                UserAppRole.role_id.in_(role_ids),
            ).all()
            dispatcher_admin_ids = {r.user_id for r in rows}

    recipient_ids = active_tech_ids | dispatcher_admin_ids
    if not recipient_ids:
        logger.warning(
            "[maint-sla] No hay destinatarios para alerta de ticket #%s",
            ticket.ticket_number,
        )
        ticket.sla_alert_sent_at = now
        return 0

    due_str = ticket.due_at.strftime('%d/%m %H:%M') if ticket.due_at else '?'

    # Intentar renderizar desde plantilla BD; fallback a strings hardcoded originales
    try:
        from itcj2.apps.maint.services.notification_helper import render_notification
        _overdue_context = {
            'ticket': ticket,
            'due_str': due_str,
        }
        _rendered = render_notification(
            db=db,
            code='ticket_overdue_sla',
            context=_overdue_context,
            fallback_title=f'Ticket vencido #{ticket.ticket_number}',
            fallback_body=f'{ticket.title[:100]} — venció {due_str}',
        )
        _title = _rendered['title']
        _body = _rendered['body']
    except Exception as _render_exc:
        logger.warning(
            "[maint-sla] render_notification falló para ticket_overdue_sla, usando fallback: %s",
            _render_exc,
        )
        _title = f'Ticket vencido #{ticket.ticket_number}'
        _body = f'{ticket.title[:100]} — venció {due_str}'

    count = 0
    for user_id in recipient_ids:
        try:
            NotificationService.create(
                db=db,
                user_id=user_id,
                app_name='maint',
                type='TICKET_OVERDUE',
                title=_title,
                body=_body,
                data={
                    'ticket_id': ticket.id,
                    'url': f'{_BASE_URL}/{ticket.id}',
                    'priority': ticket.priority,
                    'due_at': ticket.due_at.isoformat() if ticket.due_at else None,
                },
                ticket_id=ticket.id,
            )
            count += 1
        except Exception as exc:
            logger.warning(
                "[maint-sla] No se pudo crear notificación para user %s, ticket #%s: %s",
                user_id, ticket.ticket_number, exc,
            )

    # ── Broadcast WebSocket ────────────────────────────────────────────────
    # Importación local para evitar circular en tiempo de módulo
    try:
        from itcj2.sockets.maint import broadcast_ticket_status_changed

        department_id = getattr(ticket, 'requester_department_id', None)
        ws_payload = {
            'ticket_id': ticket.id,
            'ticket_number': ticket.ticket_number,
            'title': ticket.title,
            'status': ticket.status,
            'priority': ticket.priority,
            'due_at': ticket.due_at.isoformat() if ticket.due_at else None,
            'is_overdue': True,
            'sla_overdue': True,
        }
        _async_broadcast(
            broadcast_ticket_status_changed(
                ticket.id,
                list(active_tech_ids),
                ws_payload,
                department_id=department_id,
            )
        )
    except Exception as exc:
        logger.warning(
            "[maint-sla] Broadcast WS falló para ticket #%s: %s",
            ticket.ticket_number, exc,
        )

    # ── Marcar alerta enviada ──────────────────────────────────────────────
    ticket.sla_alert_sent_at = now

    logger.info(
        "[maint-sla] TICKET_OVERDUE enviado a %d destinatarios para #%s",
        count, ticket.ticket_number,
    )
    return count


def run_overdue_check(db: Session) -> dict:
    """
    Orquestador: encuentra todos los tickets vencidos y envía alertas en un pase.
    El commit se emite una única vez al final (no dentro de notify_overdue).

    Retorna un dict con el resumen de la ejecución para ser impreso como JSON
    por el script de cron.
    """
    now = now_local()
    overdue = find_overdue_tickets(db)

    if not overdue:
        return {
            'checked_at': now.isoformat(),
            'found': 0,
            'notified_total': 0,
        }

    total = 0
    for ticket in overdue:
        try:
            count = notify_overdue(db, ticket)
            total += count
        except Exception as exc:
            logger.exception(
                "[maint-sla] Error notificando ticket vencido %s: %s",
                ticket.id, exc,
            )

    db.commit()

    return {
        'checked_at': now.isoformat(),
        'found': len(overdue),
        'notified_total': total,
        'ticket_numbers': [t.ticket_number for t in overdue],
    }
