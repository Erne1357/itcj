"""Helper de correo de TitulaTec. Calcado de `apps/maint/services/email_helper.py`.

Contrato, idéntico al de maint: **ningún método lanza**. Todos devuelven `bool`.
Un fallo de correo no puede tumbar una acción: quien llama commitea primero y
manda después, así que un buzón caído no revierte nada. Cuando la liga de
activación no sale, la bandeja lo muestra como "correo no enviado" y ofrece
reenviarla.

== Cómo habilitarlo ==
1. Ir a /itcj/config/email, localizar la app "titulatec" y "Conectar".
2. Completar el OAuth delegado con la cuenta institucional que enviará.
3. El token queda en instance/apps/titulatec/email/msal_cache.json.

Mientras no esté conectado rige E9 (abajo).

== A qué buzón va cada correo (2026-09-15) ==
El destinatario lo decide CADA MÉTODO, nunca el llamador: ninguno recibe `to`.

  send_verify_enrollment    liga de activación              correo PERSONAL (req.contact_email)
  send_enrollment_approved  usuario + NIP de cuenta nueva   correo PERSONAL
  send_enrollment_rejected  motivo del rechazo              correo PERSONAL
  send_already_enrolled     "ya tienes un proceso"          INSTITUCIONAL (student_email(user))
  send_enrollment_done      folio al activarse la cuenta    INSTITUCIONAL

La liga de una cuenta existente viaja al correo que se tecleó en el formulario
público. Es un riesgo aceptado, y la contención vive en `EnrollmentRequestService`:
la cuenta no se toca, y el aviso con folio va al institucional como alarma. Los
dos correos al institucional nunca pueden salir de `req.contact_email`: le
contarían a un extraño quién se está titulando (E8).

== E9: fallback de desarrollo ==
Sin token de Graph y con `FLASK_ENV != "production"`, la liga se escribe al log
con la marca `[TT-VERIFY-LINK]`. Sin esto el flujo es imposible de probar a mano
en local. En producción, jamás: una liga de activación en el log es una
credencial en texto claro.
"""
import logging

from jinja2 import TemplateNotFound
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

APP_KEY = "titulatec"

_BASE_URL = "https://enlinea.cdjuarez.tecnm.mx/titulatec"
_STUDENT_URL = f"{_BASE_URL}/student/dashboard"


def _get_templates():
    """Importación diferida: `pages/nav.py` ya tiene el directorio configurado."""
    from itcj2.apps.titulatec.pages.nav import titulatec_templates
    return titulatec_templates


def _is_production() -> bool:
    """`True` salvo que el entorno diga explícitamente que no lo es.

    Ante la duda NO se filtra la liga: fallar hacia "esto es producción" es la
    única dirección segura para un secreto.
    """
    try:
        from itcj2.config import get_settings
        return get_settings().FLASK_ENV == "production"
    except Exception:
        return True


def _acquire_token(que: str) -> str | None:
    """Token de Graph para 'titulatec'. Avisa al log si no está conectado."""
    from itcj2.core.utils.msgraph_mail import acquire_token_silent
    token = acquire_token_silent(APP_KEY)
    if token is None:
        logger.warning(
            "Cuenta de correo de titulatec no conectada — se omite el envío de %s",
            que,
        )
    return token


def _dev_link(to: str | None, link: str | None) -> None:
    """E9: la liga al log SOLO fuera de producción."""
    if not link or _is_production():
        return
    logger.warning("[TT-VERIFY-LINK] %s -> %s", to or "(sin destinatario)", link)


def _render(template_name: str, context: dict) -> str | None:
    """Renderiza una plantilla de correo. `None` si no existe o si revienta."""
    try:
        tmpl = _get_templates().get_template(f"titulatec/email/{template_name}")
        return tmpl.render(**context)
    except TemplateNotFound:
        logger.error("Plantilla de correo no encontrada: titulatec/email/%s",
                     template_name)
        return None
    except Exception:
        logger.exception("Error renderizando titulatec/email/%s", template_name)
        return None


def _send(token: str, subject: str, html: str, recipient_email: str) -> bool:
    """Envía. `True` con HTTP 200/202. Nunca lanza."""
    from itcj2.core.utils.msgraph_mail import graph_send_mail
    try:
        r = graph_send_mail(token, subject, html, [recipient_email])
        if r.status_code in (200, 202):
            return True
        logger.warning("graph_send_mail devolvió %s para %s: %s",
                       r.status_code, recipient_email, r.text[:200])
        return False
    except Exception:
        logger.exception("Error en graph_send_mail para %s", recipient_email)
        return False


def _deliver(*, template: str, context: dict, subject: str, to: str | None,
             que: str, link: str | None = None) -> bool:
    """Tubería común: destinatario → token (o E9) → plantilla → envío."""
    if not to:
        logger.debug("Sin destinatario — se omite el envío de %s", que)
        return False
    token = _acquire_token(que)
    if token is None:
        _dev_link(to, link)
        return False
    html = _render(template, context)
    if html is None:
        return False
    ok = _send(token, subject, html, to)
    if ok:
        logger.info("[titulatec] %s -> %s", que, to)
    return ok


class TitulaTecEmailHelper:
    """Correos transaccionales de la inscripción. Ninguno lanza y ninguno deja que
    el llamador elija el destinatario."""

    @staticmethod
    def send_verify_enrollment(db: Session, req, *, link: str) -> bool:
        """Liga de ACTIVACIÓN de una cuenta que ya existe, al correo PERSONAL de la
        solicitud. La emite la bandeja al aprobar o al reenviar; abrirla inscribe
        a la cuenta (`EnrollmentRequestService.verify`). Firmada por quien revisa
        según el modo (`EnrollmentRequestService.reviewer_label()`), igual que
        `send_enrollment_rejected`."""
        try:
            from itcj2.apps.titulatec.services.enrollment_request_service import (
                EnrollmentRequestService,
            )
            dias = EnrollmentRequestService.link_ttl_days()
            return _deliver(
                template="verify_enrollment.html",
                context={"req": req, "link": link, "dias": dias,
                         "revisor": EnrollmentRequestService.reviewer_label()},
                subject="[TitulaTec ITCJ] Activa tu acceso a titulación",
                to=req.contact_email, que="verify_enrollment", link=link,
            )
        except Exception:
            logger.exception("[titulatec] Error inesperado en send_verify_enrollment")
            return False

    @staticmethod
    def send_already_enrolled(db: Session, user, process) -> bool:
        """Rama "ya tiene proceso vivo". Va al institucional, que es un buzón
        cuya posesión ya está probada: la PANTALLA pública no lo dice nunca
        (sería un oráculo anónimo de quién se está titulando, E8)."""
        try:
            from itcj2.apps.titulatec.models import Cohort
            from itcj2.core.utils.email_tools import student_email
            cohort = db.get(Cohort, process.cohort_id)
            return _deliver(
                template="already_enrolled.html",
                context={"user": user, "process": process, "cohort": cohort,
                         "app_url": _STUDENT_URL},
                subject="[TitulaTec ITCJ] Ya tienes un proceso de titulación",
                to=student_email(user), que="already_enrolled",
            )
        except Exception:
            logger.exception("[titulatec] Error inesperado en send_already_enrolled")
            return False

    @staticmethod
    def send_enrollment_done(db: Session, req, process) -> bool:
        """Cuenta existente, al abrir la liga de activación: su folio, AL
        INSTITUCIONAL. Es la alarma de la dueña de la cuenta: la liga viajó al
        correo que tecleó el solicitante, así que este aviso no puede salir de
        ahí."""
        try:
            from itcj2.core.models.user import User
            from itcj2.core.utils.email_tools import student_email
            user = db.get(User, process.student_id)
            if user is None:
                return False
            return _deliver(
                template="enrollment_done.html",
                context={"req": req, "process": process, "user": user,
                         "app_url": _STUDENT_URL},
                subject="[TitulaTec ITCJ] Tu inscripción quedó registrada",
                to=student_email(user), que="enrollment_done",
            )
        except Exception:
            logger.exception("[titulatec] Error inesperado en send_enrollment_done")
            return False

    @staticmethod
    def send_enrollment_approved(db: Session, req, user, *, nip: str | None,
                                 reassigned: bool = False,
                                 nip_source: str = "manual") -> bool:
        """Alta de una cuenta NUEVA: usuario + NIP (D16).

        Lo manda `EnrollmentRequestService._mail_access` tras dar el acceso
        (Centro de Cómputo, o la aprobación en el modo alterno) y al reasignar
        el NIP. El texto es NEUTRO sobre quién dio el acceso.

        `reassigned=True` (Reasignar NIP, D8): otro asunto y el aviso «Este NIP
        reemplaza al que te enviamos antes», para que quien sí recibió el
        primer correo sepa cuál vale.

        `nip_source="sii"` (modo `sii`, spec S4): la cuenta nació con el NIP del
        SII, que solo sabe el alumno. El correo NO lleva credencial —«entra con
        tu número de control y tu NIP del SII»— y `nip` se ignora aunque venga.

        Al correo PERSONAL: un egresado de 2005 no tiene institucional vivo. El
        NIP viaja SOLO aquí — nunca al log, ni a `X-Tt-Error`, ni al payload de
        un `ProcessEvent`.
        """
        try:
            from_sii = nip_source == "sii"
            return _deliver(
                template="enrollment_approved.html",
                context={"req": req, "user": user, "nip": None if from_sii else nip,
                         "from_sii": from_sii, "reassigned": reassigned,
                         "login_url": "https://enlinea.cdjuarez.tecnm.mx/itcj/login"},
                subject=("[TitulaTec ITCJ] Tu NIP nuevo de acceso" if reassigned
                         else "[TitulaTec ITCJ] Tu acceso a la plataforma"),
                to=req.contact_email, que="enrollment_approved",
            )
        except Exception:
            logger.exception("[titulatec] Error inesperado en send_enrollment_approved")
            return False

    @staticmethod
    def send_enrollment_rejected(db: Session, req) -> bool:
        """Rechazo con motivo, al correo personal, firmado por quien revisa según
        el modo (`EnrollmentRequestService.reviewer_label()`)."""
        try:
            from itcj2.apps.titulatec.services.enrollment_request_service import (
                EnrollmentRequestService,
            )
            return _deliver(
                template="enrollment_rejected.html",
                context={"req": req, "revisor": EnrollmentRequestService.reviewer_label()},
                subject="[TitulaTec ITCJ] Sobre tu solicitud de inscripción",
                to=req.contact_email, que="enrollment_rejected",
            )
        except Exception:
            logger.exception("[titulatec] Error inesperado en send_enrollment_rejected")
            return False
