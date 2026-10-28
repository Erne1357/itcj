"""
Correo al técnico cuando se le asigna un ticket (cola Celery, nunca en la petición).

Expone: wants_assignment_email, enqueue_assignment_email, build_assignment_email.
"""
import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

PUBLIC_ORIGIN = "https://enlinea.cdjuarez.tecnm.mx"
_DESC_MAX = 500


def wants_assignment_email(db: Session, user_id: int) -> bool:
    from itcj2.apps.helpdesk.services.helpdesk_settings_service import get_settings

    ids = get_settings(db).assignment_email_user_ids or []
    return int(user_id) in {int(i) for i in ids}


def enqueue_assignment_email(db: Session, ticket_id: int, user_id: int) -> bool:
    """Encola el correo si el técnico lo pidió. Jamás lanza."""
    try:
        if not wants_assignment_email(db, user_id):
            return False
        from itcj2.tasks.helpdesk_tasks import send_assignment_email

        send_assignment_email.delay(ticket_id, user_id)
        return True
    except Exception as e:
        logger.warning("No se pudo encolar el correo de asignación (ticket %s): %s", ticket_id, e)
        return False


def build_assignment_email(db: Session, ticket, technician) -> tuple[str, str]:
    """Devuelve (asunto, html)."""
    from itcj2.apps.helpdesk.services.notification_helper import _build_context, _safe_render
    from itcj2.apps.helpdesk.utils.catalog_cache import get_notification_template
    from itcj2.templates import templates

    subject = f"[Help Desk ITCJ] Ticket #{ticket.ticket_number} asignado a ti"
    try:
        tpl = get_notification_template(db, "ticket_assigned")
        if tpl and tpl.get("is_active") and tpl.get("subject_template"):
            # Mismo contexto que la notificación in-app (`ticket`, `assignee`):
            # la plantilla se edita una vez y sirve para los dos canales.
            subject = _safe_render(
                tpl["subject_template"], _build_context(ticket=ticket, assignee=technician),
            )
    except Exception as e:
        logger.warning("Plantilla ticket_assigned no usable, asunto por defecto: %s", e)

    desc = ticket.description or ""
    if len(desc) > _DESC_MAX:
        desc = desc[:_DESC_MAX].rstrip() + "…"
    html = templates.env.get_template("helpdesk/emails/assigned.html").render(
        ticket=ticket,
        technician=technician,
        requester=ticket.requester,
        category_name=ticket.category.name if ticket.category else "—",
        department_name=ticket.requester_department.name if ticket.requester_department else "—",
        description=desc,
        ticket_url=f"{PUBLIC_ORIGIN}/help-desk/user/tickets/{ticket.id}",
    )
    return subject, html
