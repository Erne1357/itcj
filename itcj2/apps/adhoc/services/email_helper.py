"""Correo transaccional de Adhoc (Calidad) por Microsoft Graph.

Clon del patrón de ``itcj2/apps/maint/services/email_helper.py``
(``_acquire_token`` / ``_render`` / ``_send``): **todos los métodos devuelven
``bool`` y ninguno lanza**. Un correo que no sale nunca debe abortar la
aprobación de un documento.

== Cómo habilitar ==
1. Ir a ``/itcj/config/email``, localizar la app "adhoc" y hacer clic en "Conectar".
2. Completar el flujo OAuth con la cuenta institucional de Calidad.
3. El token queda en ``instance/apps/adhoc/email/msal_cache.json``.

Sin ese paso los cinco ``send_*`` devuelven ``False`` siempre — que es
exactamente el bug del legacy (su ``NotificationService`` ni siquiera tenía los
métodos que el código llamaba, así que **nunca se envió un solo correo** y nadie
se enteró). Por eso el criterio de aceptación §12.11 del plan exige un envío
real de prueba.

== Gate doble ==
Se envía solo si:

* la fila singleton ``adhoc_mail_config.is_enabled`` está en ``true``
  (sembrada por DML; si falta, se asume **deshabilitado** — el legacy la creaba
  desde un GET, cosa que aquí está prohibida), **y**
* hay token de Graph disponible para la app ``adhoc``.

== Un envío por destinatario ==
El legacy metía a **todos** los validadores de un paso en el mismo ``To:``,
exponiendo los correos institucionales de unos a otros. Aquí cada destinatario
recibe su propia llamada a ``graph_send_mail``.

== Sin logo inline ==
``graph_send_mail`` del core solo manda ``subject`` / ``body`` /
``toRecipients`` / ``saveToSentItems`` — no ``attachments``, así que un
``<img src="cid:...">`` llegaría roto. Header tipográfico, como maint.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from jinja2 import TemplateNotFound
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

APP_KEY = "adhoc"
BRAND = "Calidad"
_BASE_URL = "https://enlinea.cdjuarez.tecnm.mx/adhoc"

URL_DASHBOARD = f"{_BASE_URL}/dashboard"
URL_DOCUMENTS = f"{_BASE_URL}/documentos"


# ==========================================================================
# Infraestructura
# ==========================================================================

def _get_templates():
    """Instancia Jinja2 de adhoc (import diferido: evita circulares)."""
    from itcj2.apps.adhoc.pages.render import adhoc_templates
    return adhoc_templates


def _mail_enabled(db: Session) -> bool:
    """Lee el singleton ``adhoc_mail_config``. Fail-closed si falta o falla."""
    try:
        from itcj2.apps.adhoc.models import AdhocMailConfig

        cfg = db.get(AdhocMailConfig, 1)
        if cfg is None:
            logger.warning(
                "[adhoc] adhoc_mail_config id=1 no existe — correo deshabilitado. "
                "Corre database/DML/adhoc/init/05_seed_catalogs.sql."
            )
            return False
        return bool(cfg.is_enabled)
    except Exception:
        logger.exception("[adhoc] No se pudo leer adhoc_mail_config — correo deshabilitado")
        return False


def _acquire_token(context: str) -> Optional[str]:
    """Token de Graph para la app ``adhoc``. Loguea aviso si no está conectada."""
    try:
        from itcj2.core.utils.msgraph_mail import acquire_token_silent

        token = acquire_token_silent(APP_KEY)
        if token is None:
            logger.warning(
                "[adhoc] Cuenta de correo no conectada — se omite el envío (%s)", context
            )
        return token
    except Exception:
        logger.exception("[adhoc] Error obteniendo token de Graph (%s)", context)
        return None


def _render(template_name: str, context: dict) -> Optional[str]:
    """Renderiza ``adhoc/emails/{template_name}``. ``None`` si falla.

    Inyecta siempre ``app_name`` — el legacy nunca lo pasaba y los cinco
    templates lo usaban, así que salía vacío en el cuerpo del correo.
    """
    try:
        tmpl = _get_templates().get_template(f"adhoc/emails/{template_name}")
        recipient = context.get("recipient")
        return tmpl.render(
            app_name=BRAND,
            recipient_name=_display_name(recipient) if recipient is not None else None,
            **context,
        )
    except TemplateNotFound:
        logger.error("[adhoc] Template de correo no encontrado: adhoc/emails/%s", template_name)
        return None
    except Exception:
        logger.exception("[adhoc] Error renderizando adhoc/emails/%s", template_name)
        return None


def _send(token: str, subject: str, html: str, recipient_email: str) -> bool:
    """Envía a UN destinatario. ``True`` en HTTP 200/202."""
    from itcj2.core.utils.msgraph_mail import graph_send_mail

    try:
        r = graph_send_mail(token, subject, html, [recipient_email])
        if r.status_code in (200, 202):
            return True
        logger.warning(
            "[adhoc] graph_send_mail retornó %s para %s: %s",
            r.status_code, recipient_email, r.text[:200],
        )
        return False
    except Exception:
        logger.exception("[adhoc] Error en graph_send_mail para %s", recipient_email)
        return False


def _display_name(user: Any) -> str:
    for attr in ("full_name", "name"):
        value = getattr(user, attr, None)
        if value:
            return str(value)
    first = getattr(user, "first_name", "") or ""
    last = getattr(user, "last_name", "") or ""
    full = f"{first} {last}".strip()
    return full or "usuario"


def _email_of(user: Any) -> Optional[str]:
    email = getattr(user, "email", None)
    return str(email).strip() if email and str(email).strip() else None


def _fan_out(
    db: Session,
    recipients: Iterable[Any],
    *,
    context_label: str,
    template: str,
    subject: str,
    base_context: dict,
) -> bool:
    """Un correo por destinatario. ``True`` si al menos uno salió.

    Deduplica por email: el mismo usuario en dos listas no recibe dos copias.
    """
    if not _mail_enabled(db):
        logger.debug("[adhoc] Correo deshabilitado — se omite %s", context_label)
        return False

    destinatarios = []
    vistos: set[str] = set()
    for user in recipients or []:
        if user is None:
            continue
        email = _email_of(user)
        if not email:
            logger.debug(
                "[adhoc] Destinatario id=%s sin email — omitido en %s",
                getattr(user, "id", "?"), context_label,
            )
            continue
        if email.lower() in vistos:
            continue
        vistos.add(email.lower())
        destinatarios.append((user, email))

    if not destinatarios:
        return False

    token = _acquire_token(context_label)
    if token is None:
        return False

    enviados = 0
    for user, email in destinatarios:
        html = _render(template, {**base_context, "recipient": user})
        if html is None:
            return False
        if _send(token, subject, html, email):
            enviados += 1
            logger.info("[adhoc] %s → %s", context_label, email)

    return enviados > 0


# ==========================================================================
# API pública
# ==========================================================================

class AdhocEmailHelper:
    """Correos transaccionales del SGC. Ningún método lanza; todos retornan ``bool``.

    El ``bool`` significa "salió al menos un correo". Los services lo usan solo
    para matizar el mensaje de respuesta (igual que el legacy, que distinguía si
    el correo había salido); nunca para decidir si la operación fue válida.
    """

    @staticmethod
    def send_flow_started(db: Session, document: Any, step: Any, recipients: Iterable[Any]) -> bool:
        """Aviso a los validadores del primer paso de un flujo recién iniciado."""
        try:
            return _fan_out(
                db, recipients,
                context_label=f"send_flow_started doc={getattr(document, 'id', '?')}",
                template="document_flow_started.html",
                subject=f"[{BRAND} ITCJ] Documento para revisión: {getattr(document, 'title', '')}",
                base_context={
                    "document": document,
                    "step": step,
                    "action_url": URL_DASHBOARD,
                },
            )
        except Exception:
            logger.exception("[adhoc] Error inesperado en send_flow_started")
            return False

    @staticmethod
    def send_task_assigned(db: Session, task: Any, recipients: Iterable[Any]) -> bool:
        """Aviso a los usuarios recién asignados a una tarea."""
        try:
            return _fan_out(
                db, recipients,
                context_label=f"send_task_assigned task={getattr(task, 'id', '?')}",
                template="task_assigned.html",
                subject=f"[{BRAND} ITCJ] Nueva tarea asignada",
                base_context={"task": task, "action_url": _task_url(task)},
            )
        except Exception:
            logger.exception("[adhoc] Error inesperado en send_task_assigned")
            return False

    @staticmethod
    def send_task_updated(
        db: Session,
        task: Any,
        recipients: Iterable[Any],
        *,
        action_label: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> bool:
        """Aviso de cambio de estatus/descripción o de acción de workflow."""
        try:
            etiqueta = action_label or "Actualización de tarea"
            return _fan_out(
                db, recipients,
                context_label=f"send_task_updated task={getattr(task, 'id', '?')}",
                template="task_updated.html",
                subject=f"[{BRAND} ITCJ] {etiqueta}",
                base_context={
                    "task": task,
                    "action_label": etiqueta,
                    "actor": actor,
                    "action_url": _task_url(task),
                },
            )
        except Exception:
            logger.exception("[adhoc] Error inesperado en send_task_updated")
            return False

    @staticmethod
    def send_document_rejected(
        db: Session,
        document: Any,
        recipient: Any,
        *,
        reason: Optional[str] = None,
    ) -> bool:
        """Aviso al autor de que su documento fue rechazado."""
        try:
            return _fan_out(
                db, [recipient],
                context_label=f"send_document_rejected doc={getattr(document, 'id', '?')}",
                template="document_rejected.html",
                subject=f"[{BRAND} ITCJ] Documento rechazado: {getattr(document, 'title', '')}",
                base_context={
                    "document": document,
                    "reason": reason,
                    "action_url": URL_DASHBOARD,
                },
            )
        except Exception:
            logger.exception("[adhoc] Error inesperado en send_document_rejected")
            return False

    @staticmethod
    def send_document_approved(db: Session, document: Any, recipient: Any) -> bool:
        """Aviso al autor de que su documento completó el flujo."""
        try:
            return _fan_out(
                db, [recipient],
                context_label=f"send_document_approved doc={getattr(document, 'id', '?')}",
                template="document_approved.html",
                subject=f"[{BRAND} ITCJ] Documento aprobado: {getattr(document, 'title', '')}",
                base_context={"document": document, "action_url": URL_DOCUMENTS},
            )
        except Exception:
            logger.exception("[adhoc] Error inesperado en send_document_approved")
            return False


def _task_url(task: Any) -> str:
    """URL absoluta donde se atiende la tarea (espeja ``notify._task_url``)."""
    if getattr(task, "document_id", None):
        return URL_DASHBOARD
    if getattr(task, "incident_id", None):
        return f"{_BASE_URL}/incidencias/{task.incident_id}/tareas"
    if getattr(task, "program_id", None):
        return f"{_BASE_URL}/programas/{task.program_id}/tareas"
    return URL_DASHBOARD
