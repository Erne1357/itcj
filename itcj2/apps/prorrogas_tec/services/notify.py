"""Avisos de Prórrogas: correo por Graph y notificación en la plataforma.

Ninguna función lanza: un buzón caído no revierte la acción que lo originó.
Fuera de producción la liga se escribe al log (`[PRORROGAS-LINK]`); en producción
jamás, porque una liga de invitación en el log es una credencial en texto claro.
"""
import logging
from datetime import date
from functools import cache
from pathlib import Path

from itcj2.apps.prorrogas_tec.services.events import log_event
from itcj2.apps.prorrogas_tec.services.formatting import MESES
from itcj2.apps.prorrogas_tec.services.identity import folio
from itcj2.config import get_settings
from itcj2.core.services.notification_service import NotificationService
from itcj2.core.utils import msgraph_mail

logger = logging.getLogger(__name__)

APP_KEY = "prorrogas_tec"

_AVISOS = {  # kind -> (título, plantilla del correo)
    "aceptada": ("Tu prórroga fue aceptada", "decision_aceptada.html"),
    "rechazada": ("Tu solicitud de prórroga no fue autorizada", "decision_rechazada.html"),
    "carta_lista": ("Firma tu carta compromiso", "carta_lista.html"),
    "plan_modificado": ("Tu plan de pagos cambió", "plan_modificado.html"),
    "recordatorio": ("Recordatorio de pago de tu prórroga", "recordatorio.html"),
    "firma_pendiente": ("Te falta firmar tu carta compromiso", "firma_pendiente.html"),
    "referencia_pendiente": ("Falta tu referencia bancaria", "referencia_pendiente.html"),
    "recibo_inconsistente": ("Revisa el recibo que subiste", "recibo_inconsistente.html"),
    "pago_registrado": ("Tu pago quedó registrado", "pago_registrado.html"),
    "liquidada": ("Terminaste de pagar tu prórroga", "liquidada.html"),
}
_CUERPOS = {  # cuerpo del aviso si no llega `body`; sin entrada, el comentario de la decisión
    "aceptada": "Se prepara tu plan de pagos con tu referencia bancaria. Te llegará un correo cuando esté listo.",
    "carta_lista": "Entra a Mi prórroga para firmarla.",
    "firma_pendiente": "Entra a Mi prórroga para firmarla.",
    "referencia_pendiente": "Súbela en PDF en Mi prórroga para preparar tu plan de pagos.",
    "plan_modificado": "Revisa tus nuevas fechas en Mi prórroga y firma tu nueva carta compromiso.",
}
# El logo va dentro del correo (cid): por URL, Outlook lo oculta hasta "Descargar imágenes"
# y desde desarrollo la liga ni siquiera es pública.
_LOGO_CID = "logo-itcj.png"
_LOGO = Path(__file__).resolve().parents[1] / "static" / "images" / "logo_correo.png"


@cache
def _logo() -> bytes:
    return _LOGO.read_bytes()


def titulo_recordatorio(vence: date, vencido: bool) -> str:
    """Asunto del recordatorio, sin año para que quepa en la bandeja del celular."""
    return "Tienes un pago vencido" if vencido else f"Tu próximo pago vence el {vence.day:02d} de {MESES[vence.month - 1]}"


def _is_production() -> bool:
    """Ante la duda, producción: es la única dirección segura para un secreto."""
    try:
        from itcj2.config import get_settings
        return get_settings().FLASK_ENV == "production"
    except Exception:
        return True


def send_email(*, template: str, context: dict, subject: str, to: str | None,
               link: str | None = None, attachments: list[tuple[str, bytes]] | None = None) -> bool:
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
        html = templates.env.get_template(f"prorrogas_tec/email/{template}").render(
            logo_url=f"cid:{_LOGO_CID}", **context)
        r = msgraph_mail.graph_send_mail(token, subject, html, [to], attachments=attachments,
                                         inline=[(_LOGO_CID, _logo())])
        if r.status_code in (200, 202):
            return True
        logger.warning("graph_send_mail devolvió %s para %s: %s", r.status_code, to, r.text[:200])
    except Exception:
        logger.exception("Error enviando el correo %s", template)
    return False


def notify_student(db, req, *, kind: str, link: str, body: str | None = None, titulo: str | None = None,
                   context: dict | None = None, attachments: list[tuple[str, bytes]] | None = None) -> bool:
    """Aviso al estudiante: notificación en la plataforma y correo. Nunca lanza.

    `titulo` reemplaza el de `_AVISOS` (asunto y título del aviso).
    `True` si el correo salió o si la solicitud no tiene correo (basta el aviso en la plataforma).
    Si no salió, deja `correo_no_enviado` en el historial; quien llama hace el commit.
    """
    title, template = _AVISOS[kind]
    title = titulo or title
    if body is None:
        body = _CUERPOS.get(kind, (req.decision_comment or "")[:200])
    try:
        with db.begin_nested():  # un flush fallido revierte solo este savepoint, no la sesión del llamador
            NotificationService.create(db, req.student_id, APP_KEY, f"prorroga_{kind}", title, body,
                                       data={"url": link, "request_id": req.id})
    except Exception:
        logger.exception("No se pudo crear el aviso de la solicitud %s", req.id)
    url = f"{get_settings().DOMAIN}{link}"  # en el correo la liga es absoluta; en la plataforma, relativa
    ok = send_email(template=template,
                    context={"folio": folio(req), "link": url, "comentario": req.decision_comment,
                             "adjunto": bool(attachments), **(context or {})},
                    subject=title, to=req.email, link=url, attachments=attachments) or not req.email
    if not ok:
        try:
            with db.begin_nested():
                log_event(db, event_type="correo_no_enviado", request_id=req.id, payload={"aviso": kind})
        except Exception:
            logger.exception("No se pudo anotar el correo no enviado de la solicitud %s", req.id)
    return ok
