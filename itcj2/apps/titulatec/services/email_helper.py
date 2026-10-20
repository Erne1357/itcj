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
  send_process_cancelled    inscripción revocada (sin motivo) INSTITUCIONAL + PERSONAL

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

== Correos del proceso (spec 2026-09-28) ==
No pasan por `TitulaTecEmailHelper`: los encola `StudentMail` en
`titulatec_email_outbox` y los manda el despachador (`mail_dispatch`) con
`deliver_detailed`, la misma tubería que `_deliver` pero con el motivo del
fallo (para `last_error` y el reintento). `_deliver` delega en ella. Su E9
ampliado (`[TT-MAIL]`) lo escribe el despachador, que pasa `link=None`:
`[TT-VERIFY-LINK]` queda solo para la liga de activación.

== Inscripción: 4 de los 6 por la bandeja (spec 2026-10-05 §3.7, P-D1) ==
Los que NO llevan secreto —`send_enrollment_done`, `send_enrollment_rejected`,
`send_already_enrolled` y `send_process_cancelled`— ya no se llaman en la
petición: quien los origina los ENCOLA (`StudentMail.enrollment_verified` /
`enrollment_rejected` / `already_enrolled` / `process_cancelled`) y los manda
el despachador con la MISMA plantilla, el MISMO asunto (`SUBJECT_*`) y el
MISMO destinatario de la tabla de arriba (`process_cancelled_recipients` es
de los dos caminos). Estos métodos siguen vivos para UNA cosa: la caída en
línea con `TITULATEC_EMAIL_ENABLED` apagado (invariante 5: ningún flujo de
inscripción se queda sin correo). `send_verify_enrollment` y
`send_enrollment_approved` (liga y NIP) no cambian de camino.
"""
import logging

from jinja2 import TemplateNotFound
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

APP_KEY = "titulatec"

# Origen público de las ligas que salen por correo: ÚNICA fuente en la app
# (spec 2026-09-28 C7). `enrollment_request_service.PUBLIC_BASE_URL` es su alias
# y `StudentMail.link` arma aquí las ligas del correo del proceso. Nunca sale
# del `Host` de la petición, que el cliente controla.
PUBLIC_ORIGIN = "https://enlinea.cdjuarez.tecnm.mx"

_BASE_URL = f"{PUBLIC_ORIGIN}/titulatec"
_STUDENT_URL = f"{_BASE_URL}/student/dashboard"
# El botón «Ver mi proceso» de los correos de inscripción: lo usan el envío en
# línea y el compositor del outbox (`mail_compose`), una sola fuente.
STUDENT_URL = _STUDENT_URL

# Asuntos de los 4 correos de inscripción que también pasan por el outbox: el
# envío en línea y `mail_compose` leen ESTOS, así no pueden divergir.
SUBJECT_ALREADY_ENROLLED = "[TitulaTec ITCJ] Ya tienes un proceso de titulación"
SUBJECT_ENROLLMENT_DONE = "[TitulaTec ITCJ] Tu inscripción quedó registrada"
SUBJECT_ENROLLMENT_REJECTED = "[TitulaTec ITCJ] Sobre tu solicitud de inscripción"
SUBJECT_PROCESS_CANCELLED = "[TitulaTec ITCJ] Cambio en tu inscripción a titulación"
SUBJECT_USERNAME_CHANGED = "[TitulaTec ITCJ] Tu usuario ahora es tu número de control"


def process_cancelled_recipients(db: Session, process, user) -> list[str]:
    """A quién va el aviso de revocación: el INSTITUCIONAL de la cuenta y el
    PERSONAL de la solicitud MÁS RECIENTE que convirtió el proceso (si la hubo
    —un alta por CSV no tiene—), sin repetir (sin distinguir mayúsculas) ni
    vacíos, en ese orden. Lo comparten `send_process_cancelled` (en línea) y el
    despachador del outbox: el destinatario es el mismo por los dos caminos."""
    from itcj2.apps.titulatec.models import EnrollmentRequest
    from itcj2.core.utils.email_tools import student_email

    destinos = [student_email(user)]
    req = (db.query(EnrollmentRequest)
           .filter_by(converted_process_id=process.id)
           .order_by(EnrollmentRequest.id.desc())
           .first())
    if req is not None and req.contact_email:
        destinos.append(req.contact_email)
    vistos, salida = set(), []
    for to in destinos:
        clave = (to or "").strip().lower()
        if not clave or clave in vistos:
            continue
        vistos.add(clave)
        salida.append(to)
    return salida


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


def _send(token: str, subject: str, html: str, recipients: list[str]) -> bool:
    """Envía UN mensaje de Graph a `recipients` (todos en «Para»). `True` con
    HTTP 200/202. Nunca lanza."""
    from itcj2.core.utils.msgraph_mail import graph_send_mail
    quien = ", ".join(recipients)
    try:
        r = graph_send_mail(token, subject, html, list(recipients))
        if r.status_code in (200, 202):
            return True
        logger.warning("graph_send_mail devolvió %s para %s: %s",
                       r.status_code, quien, r.text[:200])
        return False
    except Exception:
        logger.exception("Error en graph_send_mail para %s", quien)
        return False


def deliver_detailed(*, template: str, context: dict, subject: str,
                     to: str | list[str] | None, que: str,
                     link: str | None = None) -> tuple[bool, str | None]:
    """Tubería común: destinatario → token (o E9) → plantilla → envío, con el
    MOTIVO del fallo.

    `to` es un buzón o una LISTA de buzones de la MISMA persona (la revocación
    va al institucional y al personal): con lista sale UN solo mensaje de Graph
    con todos en «Para» -una llamada, un desenlace: ni dos esperas de hasta
    30 s dentro de la tarea del despachador, ni un reintento que repita el
    correo a quien ya lo recibió-. Vacíos se ignoran.

    `(True, None)` si salió; si no, `(False, código)` con código:
    `"sin_destinatario"` (no hay `to`), `"cuenta_no_conectada"` (sin token de
    Graph; aquí rige E9), `"plantilla"` (no existe o revienta) o `"envio"`
    (Graph no respondió 200/202, o el envío lanzó). El despachador de los
    correos del proceso (`mail_dispatch`) lo usa para dejar un `last_error`
    legible y decidir el reintento; `_deliver` es este mismo camino reducido
    a `bool`.
    """
    destinos = [d for d in ([to] if isinstance(to, str) else (to or [])) if d]
    if not destinos:
        logger.debug("Sin destinatario — se omite el envío de %s", que)
        return False, "sin_destinatario"
    quien = ", ".join(destinos)
    token = _acquire_token(que)
    if token is None:
        _dev_link(quien, link)
        return False, "cuenta_no_conectada"
    html = _render(template, context)
    if html is None:
        return False, "plantilla"
    if not _send(token, subject, html, destinos):
        return False, "envio"
    logger.info("[titulatec] %s -> %s", que, quien)
    return True, None


def _deliver(*, template: str, context: dict, subject: str,
             to: str | list[str] | None, que: str, link: str | None = None) -> bool:
    """Tubería común: destinatario → token (o E9) → plantilla → envío. Es
    `deliver_detailed` sin el motivo: la usan los 6 correos de inscripción."""
    return deliver_detailed(template=template, context=context, subject=subject,
                            to=to, que=que, link=link)[0]


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
                subject=SUBJECT_ALREADY_ENROLLED,
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
                subject=SUBJECT_ENROLLMENT_DONE,
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
    def send_username_changed(user, process, *, old_control: str,
                              personal_emails: list[str]) -> tuple[bool, str | None]:
        """Aviso de `titulatec fix-control-l` (2026-10-09): su cuenta pasó de
        «L########» a su número de control de siempre. Al institucional y a los
        correos personales que la persona escribió (UN mensaje, como la
        revocación). No lleva NIP: sigue siendo el del SII. Nunca lanza;
        devuelve `(salió, motivo)` de `deliver_detailed`."""
        try:
            from itcj2.core.utils.email_tools import student_email
            destinos = list(dict.fromkeys(
                d for d in [student_email(user), *personal_emails] if d))
            return deliver_detailed(
                template="username_changed.html",
                context={"user": user, "process": process, "old_control": old_control,
                         "app_url": _STUDENT_URL},
                subject=SUBJECT_USERNAME_CHANGED, to=destinos, que="username_changed",
            )
        except Exception:
            logger.exception("[titulatec] Error inesperado en send_username_changed")
            return False, "envio"

    @staticmethod
    def send_process_cancelled(db: Session, process) -> bool:
        """Aviso de inscripción REVOCADA (`ProcessService.cancel`). `True` si
        salió.

        A los DOS buzones: el INSTITUCIONAL de la cuenta y el PERSONAL de la
        solicitud que la convirtió (si la hubo — un alta por CSV no tiene). Un
        egresado de años atrás no lee el institucional, y el personal es por
        donde llegó todo lo anterior de este mismo trámite.

        **Sin datos sensibles**: ni el motivo, ni el folio, ni el número de
        control. El personal lo tecleó quien llenó el formulario (riesgo
        aceptado del módulo), así que el correo solo dice que hubo un cambio y
        manda a la plataforma, donde el motivo se lee con sesión iniciada.

        Los destinatarios los decide `process_cancelled_recipients`, el MISMO
        que usa el despachador del outbox, y van en UN solo mensaje (los dos
        en «Para»; es la misma persona), igual que desde el outbox.
        """
        try:
            from itcj2.core.models.user import User

            user = db.get(User, process.student_id)
            if user is None:
                return False
            return _deliver(
                template="process_cancelled.html",
                context={"first_name": user.first_name, "app_url": _STUDENT_URL},
                subject=SUBJECT_PROCESS_CANCELLED,
                to=process_cancelled_recipients(db, process, user),
                que="process_cancelled",
            )
        except Exception:
            logger.exception("[titulatec] Error inesperado en send_process_cancelled")
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
                subject=SUBJECT_ENROLLMENT_REJECTED,
                to=req.contact_email, que="enrollment_rejected",
            )
        except Exception:
            logger.exception("[titulatec] Error inesperado en send_enrollment_rejected")
            return False
