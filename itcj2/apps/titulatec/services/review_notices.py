"""Avisos in-app y correos de la revisión de sinodales (fase 5).

Spec 2026-10-22-titulatec-fase5-revision-sinodales §10 (D8 y D9). Vive aparte de
`review_service.py` (ya es el archivo más grande del motor): el servicio solo
llama aquí en tres puntos (`post_message`, `upload_version`, `vote`).

Reglas:

- **En la campana** (`NotificationService`, `app_name="titulatec"`): al alumno,
  mensaje nuevo (`REVIEW_MESSAGE`) y voto (`REVIEW_VOTE`); a los sinodales
  vigentes, versión nueva (`REVIEW_VERSION`), mensaje nuevo (`REVIEW_MESSAGE`) y
  recordatorio (`REVIEW_REMINDER`). De mensajes, **a lo más un aviso sin leer por
  conversación y usuario**. Los avisos de mensaje y voto se crean DENTRO de la
  transacción del servicio (sin commit, en un SAVEPOINT: un aviso que falla no
  tumba el mensaje ni el voto).
- **Correo al sinodal** (versión nueva, recordatorios): `deliver_detailed`
  directo, DESPUÉS del commit, best-effort, con sesión propia (patrón de
  `SynodalService.send_assignment_notices`). Una falla queda en el log y en la
  bitácora (`review.mail_failed`) y nunca revierte nada.
- **Correo al alumno** (cambios pedidos): NUNCA directo; entra por la bandeja
  (`StudentMail.review_changes_requested`, en la transacción del voto).
- Con el corte a T-soft en la fase 5 o antes no sale nada.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Tipos de notificación (literales, como el resto de la app).
MESSAGE_TYPE = "REVIEW_MESSAGE"
VOTE_TYPE = "REVIEW_VOTE"
VERSION_TYPE = "REVIEW_VERSION"
REMINDER_TYPE = "REVIEW_REMINDER"

STUDENT_PATH = "/titulatec/student/revision"
SYNODAL_PATH = "/titulatec/admin/revisiones/{process_id}"

VERSION_TEMPLATE = "review_new_version.html"     # relativa a `titulatec/email/`
VERSION_SUBJECT = "[TitulaTec ITCJ] Versión nueva del proyecto a revisar"

_ROLE_ORDER_FALLBACK = 99


def _name(user) -> str:
    if user is None:
        return ""
    return " ".join(p for p in (user.first_name, user.last_name, user.middle_name) if p)


class ReviewNotices:
    """Avisos y correos de la revisión de sinodales."""

    MESSAGE_TYPE = MESSAGE_TYPE
    VOTE_TYPE = VOTE_TYPE
    VERSION_TYPE = VERSION_TYPE
    REMINDER_TYPE = REMINDER_TYPE
    STUDENT_PATH = STUDENT_PATH
    SYNODAL_PATH = SYNODAL_PATH

    # ------------------------------------------------------------------
    # Piezas comunes
    # ------------------------------------------------------------------
    @staticmethod
    def synodal_url(process_id: int) -> str:
        return SYNODAL_PATH.format(process_id=process_id)

    @staticmethod
    def active_synodals(db: Session, process_id: int) -> list[tuple[int, int, str]]:
        """`(assignment_id, user_id, role)` de las asignaciones VIGENTES, en el
        orden del oficio. Una consulta."""
        from itcj2.apps.titulatec.models import SynodalAssignment
        from itcj2.apps.titulatec.services.synodal_service import ROLES

        filas = (db.query(SynodalAssignment.id, SynodalAssignment.user_id,
                          SynodalAssignment.role)
                 .filter(SynodalAssignment.process_id == process_id,
                         SynodalAssignment.is_active.is_(True))
                 .all())
        orden = {r: i for i, r in enumerate(ROLES)}
        return sorted(filas, key=lambda f: (orden.get(f.role, _ROLE_ORDER_FALLBACK), f.id))

    @staticmethod
    def _has_unread(db: Session, user_id: int, process_id: int, type_: str) -> bool:
        """¿`user_id` ya tiene un aviso `type_` SIN LEER de este proceso?"""
        from itcj2.core.models.notification import Notification

        return (db.query(Notification.id)
                .filter(Notification.user_id == user_id,
                        Notification.app_name == "titulatec",
                        Notification.type == type_,
                        Notification.is_read.is_(False),
                        Notification.data["process_id"].astext == str(process_id))
                .first()) is not None

    @staticmethod
    def _notify(db: Session, user_id: int, *, type_: str, title: str, body: str | None,
                url: str, process_id: int, once: bool = False) -> bool:
        """Crea el aviso en un SAVEPOINT (sin commit). `once` = no crear si el
        destinatario ya tiene uno igual sin leer de este proceso. Best-effort:
        devuelve `False` si no se creó."""
        try:
            with db.begin_nested():
                if once and ReviewNotices._has_unread(db, user_id, process_id, type_):
                    return False
                from itcj2.core.services.notification_service import NotificationService

                NotificationService.create(
                    db, user_id=user_id, app_name="titulatec", type=type_, title=title,
                    body=body, data={"url": url, "process_id": process_id})
            return True
        except Exception:
            logger.warning("Revisión: no se creó el aviso %s para el usuario %s del proceso %s",
                           type_, user_id, process_id, exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Dentro de la transacción del servicio (sin commit)
    # ------------------------------------------------------------------
    @staticmethod
    def on_message(db: Session, process, author_id: int) -> None:
        """Mensaje nuevo: avisa a los demás participantes (el alumno y los
        sinodales vigentes, menos el autor), a lo más uno sin leer por
        destinatario. Lo llama `post_message` antes de su commit."""
        pid = process.id
        es_alumno = author_id == process.student_id
        titulo_alumno = "Mensaje nuevo en la revisión de tu proyecto"
        if not es_alumno:
            ReviewNotices._notify(
                db, process.student_id, type_=MESSAGE_TYPE, title=titulo_alumno,
                body="Un sinodal escribió en la conversación de tu revisión.",
                url=STUDENT_PATH, process_id=pid, once=True)
        for _aid, uid, _role in ReviewNotices.active_synodals(db, pid):
            if uid == author_id:
                continue
            ReviewNotices._notify(
                db, uid, type_=MESSAGE_TYPE, title="Mensaje nuevo en una revisión",
                body=("El alumno escribió en la conversación de su revisión." if es_alumno
                      else "Un sinodal escribió en la conversación de la revisión."),
                url=ReviewNotices.synodal_url(pid), process_id=pid, once=True)

    @staticmethod
    def on_vote(db: Session, process, *, role: str, verdict: str, version: int,
                comment: str | None) -> None:
        """Voto: avisa al alumno (campana) y, si pidió cambios, encola su correo
        agrupado por versión. Lo llama `vote` dentro de su transacción."""
        from itcj2.apps.titulatec.services.student_mail import StudentMail
        from itcj2.apps.titulatec.services.synodal_service import ROLE_LABELS

        posicion = ROLE_LABELS.get(role, role)
        cambios = verdict == "changes_requested"
        ReviewNotices._notify(
            db, process.student_id, type_=VOTE_TYPE,
            title=("Tus sinodales pidieron cambios" if cambios
                   else "Un sinodal aprobó tu proyecto"),
            body=(f"El {posicion} pidió cambios en la versión {version}." if cambios
                  else f"El {posicion} aprobó la versión {version}."),
            url=STUDENT_PATH, process_id=process.id)
        if cambios:
            StudentMail.review_changes_requested(
                db, process, version=version, role_label=posicion,
                comment=(comment or "").strip())

    # ------------------------------------------------------------------
    # Versión nueva: avisos + correo a los sinodales (después del commit)
    # ------------------------------------------------------------------
    @staticmethod
    def send_version_notices(process_id: int, version_id: int) -> None:
        """Aviso in-app (`REVIEW_VERSION`) y correo `review_new_version.html` a
        cada sinodal vigente. Se llama DESPUÉS del commit de `upload_version`,
        abre su PROPIA sesión y es best-effort: nunca lanza. Sin `operable`, no
        sale nada. Los avisos se commitean antes de tocar el correo; cada correo
        que no sale queda en el log y en la bitácora (`review.mail_failed`)."""
        envios, folio = [], None
        try:
            from itcj2.apps.titulatec.models import ReviewVersion, TitulationProcess
            from itcj2.apps.titulatec.services.non_working_day_service import (
                NonWorkingDayService,
            )
            from itcj2.apps.titulatec.services.review_service import ReviewService
            from itcj2.apps.titulatec.services.student_mail import StudentMail
            from itcj2.apps.titulatec.services.synodal_service import SynodalService
            from itcj2.apps.titulatec.utils.dates_es import dia_largo
            from itcj2.core.models.user import User
            from itcj2.database import SessionLocal

            db = SessionLocal()
            try:
                if not ReviewService.operable(db):
                    return
                process = db.get(TitulationProcess, process_id)
                version = db.get(ReviewVersion, version_id)
                if process is None or version is None:
                    return
                folio = process.folio
                numero = version.number
                base = SynodalService._notice_base(db, process)
                vence = dia_largo(ReviewService.due_date(
                    version, holidays=NonWorkingDayService.holidays(db)))
                liga = StudentMail.link(ReviewNotices.synodal_url(process_id))
                filas = ReviewNotices.active_synodals(db, process_id)
                users = {u.id: u for u in db.query(User).filter(
                    User.id.in_([f.user_id for f in filas])).all()} if filas else {}
                for _aid, uid, _role in filas:
                    user = users.get(uid)
                    if user is None:
                        continue
                    ReviewNotices._notify(
                        db, uid, type_=VERSION_TYPE, title="Versión nueva para revisar",
                        body=f"{base['alumno']} subió la versión {numero} de su proyecto.",
                        url=ReviewNotices.synodal_url(process_id), process_id=process_id)
                    envios.append((uid, (user.email or "").strip() or None,
                                   {**base, "nombre": _name(user), "version": numero,
                                    "vence": vence, "link": liga}))
                db.commit()
            except Exception:
                db.rollback()
                envios = []
                logger.exception("Revisión: no se crearon los avisos de la versión %s del "
                                 "proceso %s", version_id, process_id)
            finally:
                db.close()
        except Exception:
            logger.exception("Revisión: error inesperado al preparar los avisos de la "
                             "versión %s del proceso %s", version_id, process_id)
            return
        ReviewNotices.deliver(envios, template=VERSION_TEMPLATE, subject=VERSION_SUBJECT,
                              que="review_version", process_id=process_id, folio=folio)

    # ------------------------------------------------------------------
    # Envío best-effort (compartido con los recordatorios)
    # ------------------------------------------------------------------
    @staticmethod
    def deliver(envios, *, template: str, subject: str, que: str, process_id: int,
                folio) -> list:
        """Manda cada `(user_id, destino, contexto)` con `deliver_detailed`. Una
        falla (o una excepción) no corta el lote: queda en el log y, todas
        juntas, en la bitácora (`review.mail_failed`). Devuelve las fallas
        `[(user_id, motivo)]`."""
        from itcj2.apps.titulatec.services import email_helper

        fallas = []
        for uid, destino, contexto in envios:
            try:
                ok, motivo = email_helper.deliver_detailed(
                    template=template, context=contexto, subject=subject,
                    to=destino, que=que)
            except Exception:
                logger.exception("Revisión: error al enviar el correo %s al usuario %s",
                                 que, uid)
                ok, motivo = False, "error"
            if not ok:
                logger.warning("Revisión: no salió el correo %s al usuario %s del proceso "
                               "%s (%s)", que, uid, process_id, motivo)
                fallas.append((uid, motivo))
        if fallas:
            ReviewNotices._record_mail_failures(process_id, folio, que, fallas)
        return fallas

    @staticmethod
    def _record_mail_failures(process_id: int, folio, que: str, fallas) -> None:
        """Cada correo que no salió, a la bitácora. Su propia sesión y su propio
        commit; si esto también falla, ya quedó en el log."""
        try:
            from itcj2.apps.titulatec.services.audit_service import AuditService
            from itcj2.database import SessionLocal

            db = SessionLocal()
            try:
                for uid, motivo in fallas:
                    AuditService.record(
                        db, "review.mail_failed",
                        entity_type="user", entity_id=uid,
                        process_id=process_id, subject=folio,
                        payload={"kind": que, "error": motivo},
                    )
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
        except Exception:
            logger.exception("Revisión: no se pudo registrar en la bitácora el fallo del "
                             "correo %s del proceso %s", que, process_id)
