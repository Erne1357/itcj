"""Helper de correo de TitulaTec. Calcado de `apps/maint/services/email_helper.py`.

Contrato, idéntico al de maint: **ningún método lanza**. Todos devuelven `bool`.
Un fallo de correo no puede tumbar una inscripción — la solicitud queda escrita
con `verify_sent_at = NULL`, la bandeja muestra "correo no enviado" y ofrece
reenvío. Nunca se pierde el registro por un problema de buzón.

== Cómo habilitarlo ==
1. Ir a /itcj/config/email, localizar la app "titulatec" y "Conectar".
2. Completar el OAuth delegado con la cuenta institucional que enviará.
3. El token queda en instance/apps/titulatec/email/msal_cache.json.

Hoy ese directorio está VACÍO: en producción la verificación no llegaría aunque
todo lo demás funcione. Mientras tanto rige E9 (abajo).

== D17: a qué buzón va el token ==
`verify_recipient` es el único lugar donde vive la regla. Alumno **conocido**:
su correo institucional, que sale de la BD (`student_email`) y NUNCA de la
petición. El número de control son 8 dígitos adivinables y públicos: si el token
saliera al buzón tecleado en el formulario, cualquiera inscribiría a un tercero
y —por D5— lo dejaría bloqueado para inscribirse de verdad. Alumno
**desconocido**: el personal que declaró, porque no existe ninguna otra
dirección suya en el mundo. Un conocido cuyo institucional no responde tras 3
envíos cae a la bandeja de Servicios Escolares; su token jamás se redirige.

== E9: fallback de desarrollo ==
Sin token de Graph y con `FLASK_ENV != "production"`, la liga se escribe al log
con la marca `[TT-VERIFY-LINK]`. Sin esto el flujo es imposible de probar a mano
en local. En producción, jamás: un token de un solo uso en el log es una
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
    única dirección segura para un secreto de un solo uso.
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
    """Correos transaccionales de la convocatoria abierta. Ninguno lanza."""

    @staticmethod
    def verify_recipient(db: Session, req) -> str | None:
        """Buzón al que va el token de verificación de `req` (D17).

        `kind='known'` → institucional del usuario, resuelto contra la BD.
        `kind='unknown'` → el personal que declaró.
        `None` si es `known` y no hay usuario con ese control: ese caso es de
        bandeja, y el token NO se redirige al personal.
        """
        try:
            if req.kind == "unknown":
                return req.contact_email or None
            from itcj2.core.models.user import User
            from itcj2.core.utils.email_tools import student_email
            user = (db.query(User)
                    .filter(User.control_number == req.control_number).first())
            if user is None:
                return None
            return student_email(user) or None
        except Exception:
            logger.exception("[titulatec] Error resolviendo destinatario de %s",
                             getattr(req, "control_number", "?"))
            return None

    @staticmethod
    def send_verify_enrollment(db: Session, req, *, to: str, link: str) -> bool:
        """Liga que CONVIERTE la solicitud. El destinatario lo resuelve el
        llamador con `verify_recipient` (D17)."""
        try:
            return _deliver(
                template="verify_enrollment.html",
                context={"req": req, "link": link, "horas": 48},
                subject="[TitulaTec ITCJ] Confirma tu inscripción",
                to=to, que="verify_enrollment", link=link,
            )
        except Exception:
            logger.exception("[titulatec] Error inesperado en send_verify_enrollment")
            return False

    @staticmethod
    def send_confirm_contact(db: Session, req, *, to: str, link: str) -> bool:
        """Segunda liga, al correo PERSONAL. No bloquea la inscripción (D17)."""
        try:
            return _deliver(
                template="confirm_contact.html",
                context={"req": req, "link": link},
                subject="[TitulaTec ITCJ] Confirma tu correo de contacto",
                to=to, que="confirm_contact", link=link,
            )
        except Exception:
            logger.exception("[titulatec] Error inesperado en send_confirm_contact")
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
        """Conocido, tras verificar: su folio. Al institucional."""
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
    def send_enrollment_approved(db: Session, req, user, *, nip: str) -> bool:
        """Alta del egresado aprobado: usuario + NIP + cambio obligatorio (D16).

        Al correo PERSONAL: un egresado de 2005 no tiene institucional vivo. El
        NIP viaja SOLO aquí — nunca al log, ni a `X-Tt-Error`, ni al payload de
        un `ProcessEvent`.
        """
        try:
            return _deliver(
                template="enrollment_approved.html",
                context={"req": req, "user": user, "nip": nip,
                         "login_url": "https://enlinea.cdjuarez.tecnm.mx/itcj/login"},
                subject="[TitulaTec ITCJ] Tu acceso a la plataforma",
                to=req.contact_email, que="enrollment_approved",
            )
        except Exception:
            logger.exception("[titulatec] Error inesperado en send_enrollment_approved")
            return False

    @staticmethod
    def send_enrollment_rejected(db: Session, req) -> bool:
        """Rechazo con motivo, al correo personal."""
        try:
            return _deliver(
                template="enrollment_rejected.html",
                context={"req": req},
                subject="[TitulaTec ITCJ] Sobre tu solicitud de inscripción",
                to=req.contact_email, que="enrollment_rejected",
            )
        except Exception:
            logger.exception("[titulatec] Error inesperado en send_enrollment_rejected")
            return False
