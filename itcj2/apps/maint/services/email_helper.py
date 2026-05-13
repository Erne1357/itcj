"""
Helper de correo electrónico para la app de Mantenimiento.

Envía notificaciones transaccionales por email usando Microsoft Graph (cuenta
propia de la app maint, almacenada bajo instance/apps/maint/email/).

== Cómo habilitar ==
1. Ir a /itcj/config/email, localizar la app "maint" y hacer clic en "Conectar".
2. Completar el flujo OAuth con la cuenta de correo institucional deseada.
3. El token queda persistido en instance/apps/maint/email/msal_cache.json.

Sin ese paso, todas las llamadas a send_* loguean un aviso y retornan False
sin lanzar ninguna excepción, de modo que el flujo de tickets no se interrumpe.

== Integración diferida ==
Cuando se quiera activar emails en asignación, agregar junto a la llamada
existente de MaintNotificationHelper.notify_technician_assigned(...):

    MaintEmailHelper.send_assigned(db, ticket, technician)

Del mismo modo para resolved, overdue y canceled.
"""
import logging

from jinja2 import TemplateNotFound
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_BASE_URL = "https://enlinea.cdjuarez.tecnm.mx/maint/tickets"

# Importación diferida para evitar circulares y mantener blast radius mínimo.
# maint_templates vive en pages/nav.py y ya tiene el directorio de templates
# configurado en itcj2/apps/maint/templates/.


def _get_templates():
    from itcj2.apps.maint.pages.nav import maint_templates
    return maint_templates


def _acquire_token(ticket_number: str) -> str | None:
    """Obtiene token de Graph para 'maint'. Loguea aviso si no está conectado."""
    from itcj2.core.utils.msgraph_mail import acquire_token_silent
    token = acquire_token_silent("maint")
    if token is None:
        logger.warning(
            "Maint email account not connected — skipping send for ticket #%s",
            ticket_number,
        )
    return token


def _render(template_name: str, context: dict) -> str | None:
    """Renderiza un template de email. Retorna None si el template no existe."""
    try:
        tmpl = _get_templates().get_template(f"maint/emails/{template_name}")
        return tmpl.render(**context)
    except TemplateNotFound:
        logger.error("Email template no encontrado: maint/emails/%s", template_name)
        return None
    except Exception:
        logger.exception("Error renderizando template maint/emails/%s", template_name)
        return None


def _send(token: str, subject: str, html: str, recipient_email: str) -> bool:
    """Envía el correo. Retorna True en éxito (HTTP 200/202)."""
    from itcj2.core.utils.msgraph_mail import graph_send_mail
    try:
        r = graph_send_mail(token, subject, html, [recipient_email])
        if r.status_code in (200, 202):
            return True
        logger.warning(
            "graph_send_mail retornó %s para %s: %s",
            r.status_code, recipient_email, r.text[:200],
        )
        return False
    except Exception:
        logger.exception("Error en graph_send_mail para %s", recipient_email)
        return False


class MaintEmailHelper:
    """Envío de correos transaccionales para el ciclo de vida de tickets maint.

    Todos los métodos son seguros: nunca lanzan excepciones — en caso de fallo
    loguean el error y retornan False para no interrumpir el flujo del ticket.
    """

    @staticmethod
    def send_assigned(db: Session, ticket, technician) -> bool:
        """Email al técnico recién asignado al ticket."""
        try:
            email = getattr(technician, "email", None)
            if not email:
                logger.debug(
                    "Técnico id=%s sin email — omitiendo send_assigned para #%s",
                    getattr(technician, "id", "?"), ticket.ticket_number,
                )
                return False

            token = _acquire_token(ticket.ticket_number)
            if token is None:
                return False

            html = _render("assigned.html", {
                "ticket": ticket,
                "recipient": technician,
                "ticket_url": f"{_BASE_URL}/{ticket.id}",
            })
            if html is None:
                return False

            subject = f"[Mantenimiento ITCJ] Ticket #{ticket.ticket_number} asignado a ti"
            success = _send(token, subject, html, email)
            if success:
                logger.info(
                    "[maint] send_assigned → %s para #%s",
                    email, ticket.ticket_number,
                )
            return success
        except Exception:
            logger.exception(
                "[maint] Error inesperado en send_assigned para #%s",
                getattr(ticket, "ticket_number", "?"),
            )
            return False

    @staticmethod
    def send_resolved(db: Session, ticket) -> bool:
        """Email al solicitante pidiendo calificación del servicio."""
        try:
            requester = ticket.requester
            email = getattr(requester, "email", None) if requester else None
            if not email:
                logger.debug(
                    "Solicitante sin email — omitiendo send_resolved para #%s",
                    ticket.ticket_number,
                )
                return False

            token = _acquire_token(ticket.ticket_number)
            if token is None:
                return False

            html = _render("resolved.html", {
                "ticket": ticket,
                "recipient": requester,
                "ticket_url": f"{_BASE_URL}/{ticket.id}",
            })
            if html is None:
                return False

            subject = f"[Mantenimiento ITCJ] Tu solicitud #{ticket.ticket_number} fue atendida"
            success = _send(token, subject, html, email)
            if success:
                logger.info(
                    "[maint] send_resolved → %s para #%s",
                    email, ticket.ticket_number,
                )
            return success
        except Exception:
            logger.exception(
                "[maint] Error inesperado en send_resolved para #%s",
                getattr(ticket, "ticket_number", "?"),
            )
            return False

    @staticmethod
    def send_overdue(db: Session, ticket, recipient_user) -> bool:
        """Email de alerta SLA vencido — destinado a técnicos activos y dispatchers."""
        try:
            email = getattr(recipient_user, "email", None)
            if not email:
                logger.debug(
                    "Usuario id=%s sin email — omitiendo send_overdue para #%s",
                    getattr(recipient_user, "id", "?"), ticket.ticket_number,
                )
                return False

            token = _acquire_token(ticket.ticket_number)
            if token is None:
                return False

            html = _render("overdue.html", {
                "ticket": ticket,
                "recipient": recipient_user,
                "ticket_url": f"{_BASE_URL}/{ticket.id}",
            })
            if html is None:
                return False

            subject = f"[Mantenimiento ITCJ] URGENTE — Ticket #{ticket.ticket_number} ha vencido"
            success = _send(token, subject, html, email)
            if success:
                logger.info(
                    "[maint] send_overdue → %s para #%s",
                    email, ticket.ticket_number,
                )
            return success
        except Exception:
            logger.exception(
                "[maint] Error inesperado en send_overdue para #%s",
                getattr(ticket, "ticket_number", "?"),
            )
            return False

    @staticmethod
    def send_canceled(db: Session, ticket, recipient_user) -> bool:
        """Email de cancelación al técnico activo afectado."""
        try:
            email = getattr(recipient_user, "email", None)
            if not email:
                logger.debug(
                    "Usuario id=%s sin email — omitiendo send_canceled para #%s",
                    getattr(recipient_user, "id", "?"), ticket.ticket_number,
                )
                return False

            token = _acquire_token(ticket.ticket_number)
            if token is None:
                return False

            html = _render("canceled.html", {
                "ticket": ticket,
                "recipient": recipient_user,
                "ticket_url": f"{_BASE_URL}/{ticket.id}",
            })
            if html is None:
                return False

            subject = f"[Mantenimiento ITCJ] Ticket #{ticket.ticket_number} cancelado"
            success = _send(token, subject, html, email)
            if success:
                logger.info(
                    "[maint] send_canceled → %s para #%s",
                    email, ticket.ticket_number,
                )
            return success
        except Exception:
            logger.exception(
                "[maint] Error inesperado en send_canceled para #%s",
                getattr(ticket, "ticket_number", "?"),
            )
            return False
