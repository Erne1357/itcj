"""Avisos de Prórrogas: correo por Graph y notificación en la plataforma.

Ninguna función lanza: un buzón caído no revierte la acción que lo originó.
Fuera de producción la liga se escribe al log (`[PRORROGAS-LINK]`); en producción
jamás, porque una liga de invitación en el log es una credencial en texto claro.
"""
import logging

from itcj2.config import get_settings
from itcj2.core.services.notification_service import NotificationService
from itcj2.core.utils import msgraph_mail

logger = logging.getLogger(__name__)

APP_KEY = "prorrogas_tec"

_AVISOS = {
    "aceptada": "Tu prórroga fue aceptada",
    "rechazada": "Tu solicitud de prórroga no fue autorizada",
}
_CUERPO_ACEPTADA = "Acude a la Subdirección Académica para acordar el monto y las fechas de tus pagos."


def _is_production() -> bool:
    """Ante la duda, producción: es la única dirección segura para un secreto."""
    try:
        from itcj2.config import get_settings
        return get_settings().FLASK_ENV == "production"
    except Exception:
        return True


def send_email(*, template: str, context: dict, subject: str, to: str | None,
               link: str | None = None) -> bool:
    """Manda un correo por Graph. `True` solo con HTTP 200/202. Nunca lanza."""
    try:
        if link and not _is_production():
            logger.warning("[PRORROGAS-LINK] %s -> %s", to or "(sin destinatario)", link)
        if not to:
            return False
        token = msgraph_mail.acquire_token_silent(APP_KEY)
        if token is None:
            logger.warning("Cuenta de correo de %s no conectada: se omite el envío", APP_KEY)
            return False
        from itcj2.templates import templates
        html = templates.env.get_template(f"prorrogas_tec/email/{template}").render(**context)
        r = msgraph_mail.graph_send_mail(token, subject, html, [to])
        if r.status_code in (200, 202):
            return True
        logger.warning("graph_send_mail devolvió %s para %s: %s", r.status_code, to, r.text[:200])
    except Exception:
        logger.exception("Error enviando el correo %s", template)
    return False


def notify_student(db, req, *, kind: str, link: str) -> None:
    """Aviso de decisión: notificación en la plataforma y correo. Nunca lanza."""
    title = _AVISOS[kind]
    body = _CUERPO_ACEPTADA if kind == "aceptada" else (req.decision_comment or "")[:200]
    try:
        with db.begin_nested():  # un flush fallido revierte solo este savepoint, no la sesión del llamador
            NotificationService.create(db, req.student_id, APP_KEY, f"prorroga_{kind}", title, body,
                                       data={"url": link, "request_id": req.id})
    except Exception:
        logger.exception("No se pudo crear el aviso de la solicitud %s", req.id)
    url = f"{get_settings().DOMAIN}{link}"  # en el correo la liga es absoluta; en la plataforma, relativa
    send_email(template=f"decision_{kind}.html",
               context={"folio": f"PR-{req.id:05d}", "link": url, "comentario": req.decision_comment},
               subject=title, to=req.email, link=url)
