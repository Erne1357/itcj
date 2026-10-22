"""Revisión de sinodales (fase 5): la ÚNICA puerta que mueve la fase 5.

Spec 2026-10-22-titulatec-fase5-revision-sinodales §6 (motor) y §7
(conversación). Una conversación por proceso entre el alumno y sus 4 sinodales
VIGENTES: mensajes, adjuntos, versiones del proyecto y votos por versión. Cuando
los votos que cuentan cumplen la regla de firma de la modalidad, la fase 5 se
aprueba sola y el proceso pasa a la 6 (D5), con reconfirmación de quien la
desata (D6). Del lado del motor, `approve_phase` de la fase `synodal_review`
exige la marca que abre `vote` (`PhaseService.open_door`) y que la regla se
cumpla de verdad (`PhaseService._door_state_ok` -> `rule_satisfied`); sin ella
da `PhaseService.REVIEW_ONLY_MSG`. La fase 5 no tiene rechazo.

Reglas que este servicio garantiza (las rutas solo deciden quién y qué proceso):

- **Un solo traductor de la regla** (§6.1): `counting_roles(signature_rule)`.
  Nadie fuera de este archivo lee `Modality.signature_rule`
  (`test_review_service.py`, AST). Regla desconocida o sin modalidad: falla
  cerrado (`RULE_UNKNOWN_MSG`; la revisión no puede cerrarse).
- **Candado + relectura** (patrón de `SynodalService`): las verificaciones
  corren primero SIN candado sobre lo cargado (lo común falla barato y sin
  deshacer nada) y se REPITEN bajo `PhaseService._lock_process_row` sobre lo
  releído. Desde el candado hasta el commit, cualquier error hace
  `db.rollback()` antes de re-lanzar. La decisión «este voto cierra» se toma
  SOLO bajo el candado: dos sinodales de tesis aprobando a la vez no cierran
  sin reconfirmación (`ReviewNeedsConfirmation`, nada escrito).
- **Votos por versión** (D4): solo cuenta la versión vigente (la de mayor
  `number`) y solo los votos de asignaciones VIGENTES; los de versiones
  anteriores o de sinodales sustituidos se quedan como historia.
- **Solo lectura** con la conversación cerrada (`closed_at`), el proceso fuera
  de `active` o la fase 5 fuera de `in_progress` (`CLOSED_MSG`).
- **Corte a T-soft**: con el corte en la fase 5 o antes nada se escribe
  (`INERT_MSG`).
- **Archivos**: validados (`utils/review_files.validate`) ANTES de escribir; en
  disco con nombre generado; se sirven solo resolviendo el mensaje DENTRO de la
  conversación del proceso ya autorizado (`attachment_for`).

Los avisos y correos (spec §10) viven en `review_notices.py` (`ReviewNotices`): aquí solo se
llaman en `post_message`, `upload_version` y `vote`.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.synodal_service import ROLE_LABELS, ROLES
from itcj2.apps.titulatec.services.review_notices import ReviewNotices
from itcj2.core.utils.timezone import db_now

logger = logging.getLogger(__name__)

PHASE_CODE = "synodal_review"           # fase 5 del catálogo
NEXT_PHASE_CODE = "anexo_iii"           # fase 6: el texto de liberación depende de si se opera aquí

# Regla de firma (§6.1, D3): `Modality.signature_rule` -> roles cuyo voto cuenta.
SIGNATURE_RULES = {
    "president_only": ("president",),
    "all_synodals": ROLES,
}

MAX_MESSAGE = 4000
MAX_COMMENT = 2000
WARN_BUSINESS_DAYS = 2                  # ámbar: a 2 o menos días hábiles del vencimiento

# --- Mensajes al usuario (español, para `X-Tt-Error` vía `_hdr`) -------------
INERT_MSG = "La revisión de sinodales todavía no se opera en esta app."
CLOSED_MSG = ("La revisión está cerrada: la conversación queda solo para consulta y ya no "
              "admite mensajes, versiones ni votos.")
NO_VERSION_MSG = "Todavía no hay una versión del proyecto para votar."
NOT_COUNTING_MSG = ("En esta modalidad tu voto no cuenta para liberar el proyecto; puedes "
                    "escribir observaciones y adjuntar archivos.")
NOT_PARTICIPANT_MSG = "No participas en la revisión de este proyecto."
ONLY_STUDENT_MSG = "Solo el alumno sube las versiones de su proyecto."
VERDICT_MSG = "Voto no reconocido: elige «Aprobar» o «Pedir cambios»."
COMMENT_REQUIRED_MSG = ("Para pedir cambios escribe tus observaciones (hasta "
                        f"{MAX_COMMENT} caracteres).")
COMMENT_TOO_LONG_MSG = f"El comentario no puede pasar de {MAX_COMMENT} caracteres."
RULE_UNKNOWN_MSG = "Regla de firma desconocida; avisa al Departamento de Titulación."
MESSAGE_EMPTY_MSG = "Escribe un mensaje o adjunta un archivo."
MESSAGE_TOO_LONG_MSG = f"El mensaje no puede pasar de {MAX_MESSAGE} caracteres."
CONFIRM_CLOSE_MSG = ("Al aprobar se cerrará la revisión: la conversación quedará solo para "
                     "consulta y ya no habrá más cambios ni versiones. ¿Confirmas?")
VERSION_CHANGED_MSG = "El alumno subió una versión nueva: revísala antes de votar."

# --- Textos que el sistema deja en la conversación ---------------------------
OPEN_CHAT_MSG = ("Tus sinodales quedaron asignados. Sube la primera versión de tu proyecto "
                 "para empezar la revisión.")
VERSION_TEXT = "Versión {numero} del proyecto."
VOTE_APPROVED_TEXT = "El {posicion} aprobó la versión {numero}."
VOTE_CHANGES_TEXT = "El {posicion} pidió cambios en la versión {numero}:"
RELEASED_TEXT = ("Proyecto liberado. Ya puedes pasar por tu Anexo III para que lo firmen tus "
                 "sinodales: {firmas}.")
# Mismo texto de traspaso que el correo `phase_approved` (variante `handoff`).
RELEASED_HANDOFF_TEXT = ("Proyecto liberado. Tu proceso continúa en el Departamento de "
                         "Titulación, en el sistema T-soft. El departamento te contactará por "
                         "correo para darte tu usuario.")
REPLACED_TEXT = "{nuevo} sustituye a {anterior} como {posicion}."
STUDENT_LABEL = "Alumno"


class ReviewNeedsConfirmation(ValueError):
    """Este voto cumpliría la regla y cerraría la revisión: falta reconfirmarlo
    (D6). Se levanta bajo el candado y ANTES de escribir nada."""


class ReviewVersionChanged(ValueError):
    """La versión que el sinodal tenía en pantalla ya no es la vigente. Nada se
    escribió: la ruta re-pinta la conversación con `VERSION_CHANGED_MSG`."""


def _name(first, last, middle) -> str:
    """Nombre en orden natural (nombre(s), paterno, materno)."""
    return " ".join(p for p in (first, last, middle) if p)


def _user_name(user) -> str:
    return _name(user.first_name, user.last_name, user.middle_name) if user else ""


def _to_int(raw) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _truthy(raw) -> bool:
    """`confirm` de un formulario: solo `True`, 1 o «1/true/on/yes» cuentan."""
    if isinstance(raw, bool):
        return raw
    return str(raw if raw is not None else "").strip().lower() in ("1", "true", "on", "yes")


def _display_name(original_name, ext: str) -> str:
    """Nombre para mostrar y descargar: sin carpetas, recortado a la columna."""
    base = re.split(r"[\\/]", str(original_name or ""))[-1].strip()
    return (base or f"archivo.{ext}")[:255]


def _size_label(size) -> str:
    if not size:
        return ""
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{max(1, round(size / 1024))} KB"


class ReviewService:
    """Conversación, versiones, votos y cierre de la revisión de sinodales."""

    PHASE_CODE = PHASE_CODE
    SIGNATURE_RULES = SIGNATURE_RULES
    INERT_MSG = INERT_MSG
    CLOSED_MSG = CLOSED_MSG
    NO_VERSION_MSG = NO_VERSION_MSG
    NOT_COUNTING_MSG = NOT_COUNTING_MSG
    NOT_PARTICIPANT_MSG = NOT_PARTICIPANT_MSG
    ONLY_STUDENT_MSG = ONLY_STUDENT_MSG
    VERDICT_MSG = VERDICT_MSG
    COMMENT_REQUIRED_MSG = COMMENT_REQUIRED_MSG
    COMMENT_TOO_LONG_MSG = COMMENT_TOO_LONG_MSG
    RULE_UNKNOWN_MSG = RULE_UNKNOWN_MSG
    MESSAGE_EMPTY_MSG = MESSAGE_EMPTY_MSG
    MESSAGE_TOO_LONG_MSG = MESSAGE_TOO_LONG_MSG
    CONFIRM_CLOSE_MSG = CONFIRM_CLOSE_MSG
    VERSION_CHANGED_MSG = VERSION_CHANGED_MSG

    # ------------------------------------------------------------------
    # Corte
    # ------------------------------------------------------------------
    @staticmethod
    def operable(db: Session) -> bool:
        """¿La fase 5 se opera en esta app? Falla cerrado: sin la fase en el
        catálogo, o con el corte a T-soft en ella o antes, no."""
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        n = PhaseService.phase_number_for_code(db, PHASE_CODE)
        return n is not None and PhaseService._handoff_phase() > n

    @staticmethod
    def _assert_operable(db: Session) -> int:
        """Número de la fase 5, o `ValueError(INERT_MSG)`."""
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        n = PhaseService.phase_number_for_code(db, PHASE_CODE)
        if n is None or PhaseService._handoff_phase() <= n:
            raise ValueError(INERT_MSG)
        return n

    # ------------------------------------------------------------------
    # Regla de firma (§6.1): el ÚNICO traductor
    # ------------------------------------------------------------------
    @staticmethod
    def counting_roles(signature_rule: str | None) -> tuple[str, ...]:
        """Roles cuyo voto cuenta: `president_only` -> el Presidente;
        `all_synodals` -> los 4 (suplente incluido). Desconocida o None ->
        `ValueError(RULE_UNKNOWN_MSG)` (falla cerrado)."""
        roles = SIGNATURE_RULES.get(signature_rule) if isinstance(signature_rule, str) else None
        if roles is None:
            raise ValueError(RULE_UNKNOWN_MSG)
        return tuple(roles)

    @staticmethod
    def rule_for(process) -> str | None:
        """La regla grabada en la modalidad del proceso; None sin modalidad
        (`counting_roles(None)` falla cerrado)."""
        modality = getattr(process, "modality", None)
        return modality.signature_rule if modality is not None else None

    @staticmethod
    def signature_text(signature_rule: str | None) -> str:
        """Las firmas del Anexo III en lenguaje llano, desde el traductor."""
        roles = ReviewService.counting_roles(signature_rule)
        if len(roles) == 1:
            return f"basta la firma del {ROLE_LABELS.get(roles[0], roles[0])}"
        return f"se necesitan las firmas de tus {len(roles)} sinodales"

    @staticmethod
    def rule_label(signature_rule: str | None) -> str:
        """La regla de votos para el panel de estado; desconocida ->
        `RULE_UNKNOWN_MSG`."""
        try:
            roles = ReviewService.counting_roles(signature_rule)
        except ValueError:
            return RULE_UNKNOWN_MSG
        if len(roles) == 1:
            return f"Basta la aprobación del {ROLE_LABELS.get(roles[0], roles[0])}"
        return f"Se necesita la aprobación de los {len(roles)} sinodales"

    # ------------------------------------------------------------------
    # Conversación
    # ------------------------------------------------------------------
    @staticmethod
    def _chat_of(db: Session, process_id: int, *, fresh: bool = False):
        from itcj2.apps.titulatec.models import ProcessChat

        q = db.query(ProcessChat).filter(ProcessChat.process_id == process_id)
        if fresh:
            q = q.populate_existing()
        return q.first()

    @staticmethod
    def _system_message(db: Session, chat, body: str):
        from itcj2.apps.titulatec.models import ChatMessage

        msg = ChatMessage(chat_id=chat.id, author_id=None, kind="system", body=body,
                          created_at=db_now())
        db.add(msg)
        return msg

    @staticmethod
    def open_chat(db: Session, process):
        """La conversación del proceso; si no existe la crea con su mensaje
        `system` de apertura. Sin commit (la llama `SynodalService.assign`
        dentro de su transacción, antes de `approve_phase`). Idempotente."""
        from itcj2.apps.titulatec.models import ProcessChat

        chat = ReviewService._chat_of(db, process.id)
        if chat is not None:
            return chat
        chat = ProcessChat(process_id=process.id, created_at=db_now())
        db.add(chat)
        db.flush()
        ReviewService._system_message(db, chat, OPEN_CHAT_MSG)
        db.flush()
        return chat

    @staticmethod
    def chat_for(db: Session, process, *, create: bool = False):
        """La conversación del proceso o None. Con `create=True` la crea y
        commitea si falta (respaldo para procesos que ya estaban en la fase 5
        sin conversación). Dos peticiones a la vez: la segunda relee."""
        chat = ReviewService._chat_of(db, process.id)
        if chat is not None or not create:
            return chat
        try:
            chat = ReviewService.open_chat(db, process)
            db.commit()
            return chat
        except IntegrityError:
            db.rollback()
            return ReviewService._chat_of(db, process.id)

    @staticmethod
    def _phase_status(db: Session, process_id: int) -> str | None:
        """Estado de la fase 5 del proceso (leída por código)."""
        from itcj2.apps.titulatec.models import ProcessPhase
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        n = PhaseService.phase_number_for_code(db, PHASE_CODE)
        if n is None:
            return None
        return (db.query(ProcessPhase.status)
                .filter(ProcessPhase.process_id == process_id,
                        ProcessPhase.phase_number == n).scalar())

    @staticmethod
    def is_open(process, chat) -> bool:
        """¿Se puede escribir, subir y votar? Conversación sin `closed_at`,
        proceso `active` y fase 5 `in_progress`. La fase se lee con la sesión
        del propio proceso; sin sesión, falla cerrado."""
        from sqlalchemy.orm import object_session
        from sqlalchemy.orm.exc import UnmappedInstanceError

        if chat is None or chat.closed_at is not None:
            return False
        if getattr(process, "status", None) != "active":
            return False
        try:
            db = object_session(process)
        except UnmappedInstanceError:
            return False
        if db is None:
            return False
        return ReviewService._phase_status(db, process.id) == "in_progress"

    @staticmethod
    def _assert_open(db: Session, process, *, fresh: bool):
        """La conversación abierta del proceso, o `ValueError(CLOSED_MSG)`.
        `fresh=True` (bajo el candado) relee la conversación de la BD."""
        chat = ReviewService._chat_of(db, process.id, fresh=fresh)
        if (chat is None or chat.closed_at is not None or process.status != "active"
                or ReviewService._phase_status(db, process.id) != "in_progress"):
            raise ValueError(CLOSED_MSG)
        return chat

    # ------------------------------------------------------------------
    # Participantes (§12): el alumno dueño y las asignaciones VIGENTES
    # ------------------------------------------------------------------
    @staticmethod
    def participant_role(db: Session, process_id: int, user_id: int) -> str | None:
        """Rol de la asignación VIGENTE de `user_id` en el proceso, o None."""
        from itcj2.apps.titulatec.models import SynodalAssignment

        return (db.query(SynodalAssignment.role)
                .filter(SynodalAssignment.process_id == process_id,
                        SynodalAssignment.user_id == user_id,
                        SynodalAssignment.is_active.is_(True))
                .scalar())

    @staticmethod
    def assert_participant(db: Session, user_id: int, process_id: int):
        """Guarda de las rutas del sinodal: el proceso si `user_id` tiene una
        asignación VIGENTE en él; si no, `HTTPException(404)` sin header (un
        sustituido, un extraño, un jefe o el alumno de otro proceso no saben
        siquiera si existe)."""
        from itcj2.apps.titulatec.models import TitulationProcess

        if ReviewService.participant_role(db, process_id, user_id) is None:
            raise HTTPException(status_code=404)
        process = db.get(TitulationProcess, process_id)
        if process is None:
            raise HTTPException(status_code=404)
        return process

    @staticmethod
    def _assert_author(db: Session, process, actor_id: int) -> str | None:
        """El alumno dueño (None) o el rol del sinodal vigente; si no,
        `ValueError(NOT_PARTICIPANT_MSG)`."""
        if actor_id is not None and actor_id == process.student_id:
            return None
        role = ReviewService.participant_role(db, process.id, actor_id)
        if role is None:
            raise ValueError(NOT_PARTICIPANT_MSG)
        return role

    @staticmethod
    def _active_assignment(db: Session, process_id: int, user_id: int):
        from itcj2.apps.titulatec.models import SynodalAssignment

        return (db.query(SynodalAssignment)
                .filter(SynodalAssignment.process_id == process_id,
                        SynodalAssignment.user_id == user_id,
                        SynodalAssignment.is_active.is_(True))
                .populate_existing()
                .first())

    # ------------------------------------------------------------------
    # Versiones y plazo
    # ------------------------------------------------------------------
    @staticmethod
    def current_version(db: Session, process_id: int):
        """La versión vigente: la de mayor `number`, o None."""
        from itcj2.apps.titulatec.models import ReviewVersion

        return (db.query(ReviewVersion)
                .filter(ReviewVersion.process_id == process_id)
                .order_by(ReviewVersion.number.desc())
                .first())

    @staticmethod
    def due_date(version, *, holidays: frozenset[date]) -> date:
        """Vencimiento: `review_days()` días hábiles después de la fecha de la
        versión, con el calendario de días inhábiles (no se guarda: si se
        registran días después, el plazo se recorre solo)."""
        from itcj2.apps.titulatec.utils.business_days import add_business_days
        from itcj2.apps.titulatec.utils.review_files import review_days

        return add_business_days(version.uploaded_at.date(), review_days(), holidays=holidays)

    @staticmethod
    def semaphore(due: date, *, today: date, holidays: frozenset[date]) -> str:
        """`late` vencido, `warn` a `WARN_BUSINESS_DAYS` o menos días hábiles
        (el día que vence incluido), `ok` si no."""
        from itcj2.apps.titulatec.utils.business_days import business_days_between

        if today > due:
            return "late"
        if business_days_between(today, due, holidays=holidays) <= WARN_BUSINESS_DAYS:
            return "warn"
        return "ok"

    @staticmethod
    def upload_version(db: Session, process, actor_id: int, *, raw: bytes,
                       original_name: str):
        """El alumno dueño sube la versión siguiente de su proyecto.

        Valida el archivo ANTES de escribir nada (`ReviewFileError`, subclase
        de `ValueError`); bajo el candado relee que la conversación siga
        abierta, numera (máx + 1), escribe `v{N}_{control}.{ext}`, la fila, el
        mensaje `version`, el evento `review_version_uploaded` y la bitácora, y
        commitea. Los votos de la versión anterior dejan de contar (D4)."""
        from itcj2.apps.titulatec.models import ChatMessage, ReviewVersion
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.document_service import DocumentService
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        from itcj2.apps.titulatec.utils import review_files

        if process is None or actor_id is None or actor_id != process.student_id:
            raise ValueError(ONLY_STUDENT_MSG)
        n5 = ReviewService._assert_operable(db)
        ReviewService._assert_open(db, process, fresh=False)
        ext, mime = review_files.validate(raw, original_name)
        nombre = _display_name(original_name, ext)

        try:
            PhaseService._lock_process_row(db, process)
            chat = ReviewService._assert_open(db, process, fresh=True)
            actual = (db.query(func.max(ReviewVersion.number))
                      .filter(ReviewVersion.process_id == process.id).scalar())
            numero = int(actual or 0) + 1
            period_code, control = DocumentService._storage_keys(db, process)
            ruta = review_files.write(
                raw, period_code=period_code, control_number=control,
                filename=review_files.version_filename(numero, control, ext))
            ahora = db_now()
            version = ReviewVersion(process_id=process.id, number=numero, file_path=ruta,
                                    original_name=nombre, mime_type=mime, size_bytes=len(raw),
                                    uploaded_by_id=actor_id, uploaded_at=ahora)
            db.add(version)
            db.flush()
            db.add(ChatMessage(chat_id=chat.id, author_id=actor_id, kind="version",
                               version_id=version.id, body=VERSION_TEXT.format(numero=numero),
                               attachment_name=nombre, attachment_mime=mime,
                               attachment_size=len(raw), created_at=ahora))
            PhaseService._log(db, process.id, actor_id, "review_version_uploaded", n5,
                              {"version": numero})
            AuditService.record(
                db, "review.version_uploaded",
                entity_type="process", entity_id=process.id,
                process_id=process.id, subject=process.folio,
                payload={"version": numero, "mime": mime, "size": len(raw)},
                actor_id=actor_id,
            )
            pid, vid = process.id, version.id      # antes del commit (expire_on_commit en prod)
            db.commit()
        except Exception:
            db.rollback()
            raise
        # Avisos y correos a los sinodales: después del commit, best-effort (§10).
        ReviewNotices.send_version_notices(pid, vid)
        return version

    # ------------------------------------------------------------------
    # Mensajes
    # ------------------------------------------------------------------
    @staticmethod
    def post_message(db: Session, process, actor_id: int, *, body: str | None,
                     raw: bytes | None = None, original_name: str | None = None):
        """Un mensaje del alumno o de un sinodal vigente: texto (1..4000, sin
        espacios a los lados) con o sin un adjunto PDF/Word; un adjunto solo
        también vale. El adjunto se escribe tras el `flush` (su nombre lleva el
        id del mensaje). Commit."""
        from itcj2.apps.titulatec.models import ChatMessage
        from itcj2.apps.titulatec.services.document_service import DocumentService
        from itcj2.apps.titulatec.services.phase_service import PhaseService
        from itcj2.apps.titulatec.utils import review_files

        ReviewService._assert_operable(db)
        ReviewService._assert_author(db, process, actor_id)
        texto = str(body or "").strip()
        if len(texto) > MAX_MESSAGE:
            raise ValueError(MESSAGE_TOO_LONG_MSG)
        if not texto and raw is None:
            raise ValueError(MESSAGE_EMPTY_MSG)
        ReviewService._assert_open(db, process, fresh=False)
        ext = mime = None
        if raw is not None:
            ext, mime = review_files.validate(raw, original_name or "")

        try:
            PhaseService._lock_process_row(db, process)
            chat = ReviewService._assert_open(db, process, fresh=True)
            ReviewService._assert_author(db, process, actor_id)
            msg = ChatMessage(chat_id=chat.id, author_id=actor_id, kind="message",
                              body=texto or None, created_at=db_now())
            db.add(msg)
            db.flush()
            if raw is not None:
                period_code, control = DocumentService._storage_keys(db, process)
                msg.attachment_path = review_files.write(
                    raw, period_code=period_code, control_number=control,
                    filename=review_files.attachment_filename(msg.id, control, ext))
                msg.attachment_name = _display_name(original_name, ext)
                msg.attachment_mime = mime
                msg.attachment_size = len(raw)
            ReviewNotices.on_message(db, process, actor_id)
            db.commit()
        except Exception:
            db.rollback()
            raise
        return msg

    @staticmethod
    def messages(db: Session, chat_id: int, *, after_id: int | None = None) -> list[dict]:
        """Los mensajes de la conversación por `id` (los posteriores a
        `after_id` si viene), listos para `partials/review/_messages.html`.
        Consultas fijas (3 a lo más), sin N+1: autor y versión van en la misma
        consulta; el rol del sinodal sale de sus asignaciones en el proceso (la
        vigente gana; un sustituido conserva el rol con el que escribió)."""
        from itcj2.apps.titulatec.models import (
            ChatMessage,
            ProcessChat,
            ReviewVersion,
            SynodalAssignment,
            TitulationProcess,
        )
        from itcj2.apps.titulatec.utils.dates_es import dia_mes_hora
        from itcj2.core.models.user import User

        q = (db.query(ChatMessage.id, ChatMessage.kind, ChatMessage.body,
                      ChatMessage.author_id, ChatMessage.created_at, ChatMessage.version_id,
                      ChatMessage.attachment_path, ChatMessage.attachment_name,
                      ChatMessage.attachment_mime, ChatMessage.attachment_size,
                      User.first_name, User.last_name, User.middle_name,
                      ReviewVersion.number)
             .outerjoin(User, User.id == ChatMessage.author_id)
             .outerjoin(ReviewVersion, ReviewVersion.id == ChatMessage.version_id)
             .filter(ChatMessage.chat_id == chat_id))
        despues = _to_int(after_id)
        if despues is not None:
            q = q.filter(ChatMessage.id > despues)
        filas = q.order_by(ChatMessage.id).all()
        if not filas:
            return []

        ctx = (db.query(ProcessChat.process_id, TitulationProcess.student_id)
               .join(TitulationProcess, TitulationProcess.id == ProcessChat.process_id)
               .filter(ProcessChat.id == chat_id).first())
        process_id, student_id = (ctx if ctx else (None, None))
        roles: dict[int, str] = {}
        if process_id is not None:
            for uid, role in (db.query(SynodalAssignment.user_id, SynodalAssignment.role)
                              .filter(SynodalAssignment.process_id == process_id)
                              .order_by(SynodalAssignment.is_active, SynodalAssignment.id)
                              .all()):
                roles[uid] = role          # la última gana: la vigente va al final

        salida = []
        for f in filas:
            es_alumno = f.author_id is not None and f.author_id == student_id
            role = None if es_alumno else roles.get(f.author_id)
            con_archivo = bool(f.attachment_path) or (f.kind == "version" and f.version_id)
            ext = os.path.splitext(f.attachment_name or "")[1].lstrip(".").lower()
            salida.append({
                "id": f.id,
                "kind": f.kind,
                "body": f.body,
                "author_id": f.author_id,
                "author_name": _name(f.first_name, f.last_name, f.middle_name),
                "author_role": role,
                "author_label": (STUDENT_LABEL if es_alumno
                                 else ROLE_LABELS.get(role, "") if role else ""),
                "is_student": es_alumno,
                "is_system": f.kind == "system",
                "created_at": f.created_at,
                "created_label": dia_mes_hora(f.created_at) if f.created_at else "",
                "version_id": f.version_id,
                "version_number": f.number,
                "attachment": ({
                    "name": f.attachment_name or (f"Versión {f.number}" if f.number else "Archivo"),
                    "mime": f.attachment_mime,
                    "size": f.attachment_size,
                    "size_label": _size_label(f.attachment_size),
                    "ext": ext,
                } if con_archivo else None),
            })
        return salida

    @staticmethod
    def on_replaced(db: Session, process, *, role: str, old_user_id: int,
                    new_user_id: int) -> None:
        """Mensaje `system` «X sustituye a Y como Secretario» si el proceso ya
        tiene conversación. Sin commit: lo llama `SynodalService.replace` dentro
        de su transacción. Sustituir nunca cierra la revisión."""
        from itcj2.core.models.user import User

        chat = ReviewService._chat_of(db, process.id)
        if chat is None:
            return
        ids = [u for u in (old_user_id, new_user_id) if u is not None]
        users = {u.id: u for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}
        ReviewService._system_message(db, chat, REPLACED_TEXT.format(
            nuevo=_user_name(users.get(new_user_id)) or "Otro docente",
            anterior=_user_name(users.get(old_user_id)) or "el sinodal anterior",
            posicion=ROLE_LABELS.get(role, role)))

    # ------------------------------------------------------------------
    # Votos (§6.3) y cierre (§6.4)
    # ------------------------------------------------------------------
    @staticmethod
    def _active_verdicts(db: Session, process_id: int, version_id: int | None) -> list:
        """`(role, user_id, verdict)` de cada asignación VIGENTE, con su voto en
        `version_id` (None si no votó). Una consulta."""
        from itcj2.apps.titulatec.models import ReviewVote, SynodalAssignment

        # Sin versión, el `-1` no casa con ningún voto: todos salen None.
        vid = version_id if version_id is not None else -1
        return (db.query(SynodalAssignment.role, SynodalAssignment.user_id, ReviewVote.verdict)
                .outerjoin(ReviewVote, and_(ReviewVote.assignment_id == SynodalAssignment.id,
                                            ReviewVote.version_id == vid))
                .filter(SynodalAssignment.process_id == process_id,
                        SynodalAssignment.is_active.is_(True))
                .order_by(SynodalAssignment.id).all())

    @staticmethod
    def _satisfied(roles, verdicts: dict) -> bool:
        """Todos los roles que cuentan tienen `approved` (con asignación vigente)."""
        return bool(roles) and all(verdicts.get(r) == "approved" for r in roles)

    @staticmethod
    def _vote_state(db: Session, process, actor_id: int, *, fresh: bool) -> dict:
        """Todo lo que `vote` (y `would_close`) verifican, sin escribir. Corre
        sin candado sobre lo cargado y otra vez bajo el candado (`fresh`)."""
        assignment = ReviewService._active_assignment(db, process.id, actor_id)
        if assignment is None:
            raise ValueError(NOT_PARTICIPANT_MSG)
        chat = ReviewService._assert_open(db, process, fresh=fresh)
        rule = ReviewService.rule_for(process)
        roles = ReviewService.counting_roles(rule)
        if assignment.role not in roles:
            raise ValueError(NOT_COUNTING_MSG)
        version = ReviewService.current_version(db, process.id)
        if version is None:
            raise ValueError(NO_VERSION_MSG)
        filas = ReviewService._active_verdicts(db, process.id, version.id)
        return {
            "assignment": assignment, "chat": chat, "rule": rule, "roles": roles,
            "version": version,
            "verdicts": {role: verdict for role, _uid, verdict in filas},
            "users": {role: uid for role, uid, _v in filas},
        }

    @staticmethod
    def _release_text(db: Session, rule: str) -> str:
        """Texto de liberación: Anexo III con sus firmas si la fase 6 se opera
        aquí; si no, el traspaso a T-soft de siempre (sin prometer el Anexo)."""
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        if NEXT_PHASE_CODE in PhaseService.operable_codes(db, [NEXT_PHASE_CODE]):
            return RELEASED_TEXT.format(firmas=ReviewService.signature_text(rule))
        return RELEASED_HANDOFF_TEXT

    @staticmethod
    def _vote_text(role: str, verdict: str, numero: int, comment: str) -> str:
        posicion = ROLE_LABELS.get(role, role)
        if verdict == "approved":
            texto = VOTE_APPROVED_TEXT.format(posicion=posicion, numero=numero)
            return f"{texto}\n{comment}" if comment else texto
        return f"{VOTE_CHANGES_TEXT.format(posicion=posicion, numero=numero)}\n{comment}"

    @staticmethod
    def vote(db: Session, process, actor_id: int, *, verdict: str, comment: str | None,
             seen_version: int | None, confirm: bool) -> dict:
        """El voto de un sinodal vigente cuyo voto cuenta, sobre la versión
        vigente. Devuelve `{"closed": bool, "version": int}`.

        - `seen_version` es la versión que tenía en pantalla: si ya no es la
          vigente (o no viene), `ReviewVersionChanged` sin escribir nada.
        - `changes_requested` exige comentario (1..2000); `approved` lo admite.
        - Bajo el candado: inserta o actualiza SU voto de la versión vigente, el
          mensaje `vote`, el evento `review_vote_cast` y la bitácora.
        - Si con este voto se cumple la regla: sin `confirm` ->
          `ReviewNeedsConfirmation` ANTES de escribir; con `confirm` -> cierra:
          `closed_at`, mensaje `system` de liberación y el motor
          (`open_door` + `approve_phase`, que activa la fase 6, avisa al alumno,
          encola su correo y commitea todo junto).
        """
        from itcj2.apps.titulatec.models import ChatMessage, ReviewVote
        from itcj2.apps.titulatec.models.review import VOTE_VERDICTS
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        verdict = str(verdict or "").strip()
        if verdict not in VOTE_VERDICTS:
            raise ValueError(VERDICT_MSG)
        confirm = _truthy(confirm)
        texto = str(comment or "").strip()
        if verdict == "changes_requested" and not (1 <= len(texto) <= MAX_COMMENT):
            raise ValueError(COMMENT_REQUIRED_MSG)
        if len(texto) > MAX_COMMENT:
            raise ValueError(COMMENT_TOO_LONG_MSG)
        n5 = ReviewService._assert_operable(db)
        vista = _to_int(seen_version)

        st = ReviewService._vote_state(db, process, actor_id, fresh=False)
        if vista != st["version"].number:
            raise ReviewVersionChanged(VERSION_CHANGED_MSG)

        cerro = False
        try:
            PhaseService._lock_process_row(db, process)
            st = ReviewService._vote_state(db, process, actor_id, fresh=True)
            version, role = st["version"], st["assignment"].role
            numero = version.number           # antes del commit (expire_on_commit en prod)
            if vista != numero:
                raise ReviewVersionChanged(VERSION_CHANGED_MSG)
            despues = {**st["verdicts"], role: verdict}
            cierra = ReviewService._satisfied(st["roles"], despues)
            if cierra and not confirm:
                raise ReviewNeedsConfirmation(CONFIRM_CLOSE_MSG)

            ahora = db_now()
            fila = (db.query(ReviewVote)
                    .filter(ReviewVote.version_id == version.id,
                            ReviewVote.assignment_id == st["assignment"].id)
                    .populate_existing().first())
            if fila is None:
                db.add(ReviewVote(version_id=version.id, assignment_id=st["assignment"].id,
                                  user_id=actor_id, verdict=verdict, comment=texto or None,
                                  created_at=ahora))
            else:
                fila.verdict = verdict
                fila.comment = texto or None
                fila.user_id = actor_id
            db.add(ChatMessage(chat_id=st["chat"].id, author_id=actor_id, kind="vote",
                               version_id=version.id, created_at=ahora,
                               body=ReviewService._vote_text(role, verdict, numero, texto)))
            datos = {"version": numero, "role": role, "verdict": verdict}
            PhaseService._log(db, process.id, actor_id, "review_vote_cast", n5, dict(datos))
            AuditService.record(
                db, "review.vote_cast",
                entity_type="process", entity_id=process.id,
                process_id=process.id, subject=process.folio,
                payload=dict(datos),
                actor_id=actor_id,
            )
            ReviewNotices.on_vote(db, process, role=role, verdict=verdict,
                                  version=numero, comment=texto)
            if not cierra:
                db.commit()
                return {"closed": False, "version": numero}

            st["chat"].closed_at = ahora
            ReviewService._system_message(db, st["chat"],
                                          ReviewService._release_text(db, st["rule"]))
            db.flush()
            votantes = [{"role": r, "user_id": st["users"].get(r)}
                        for r in ROLES if r in st["roles"]]
            PhaseService.open_door(db, PHASE_CODE, process.id, "approved")
            PhaseService.approve_phase(
                db, process, n5, actor_id,
                event_payload={"version": numero, "rule": st["rule"],
                               "voters": votantes})
            cerro = True
        except Exception:
            db.rollback()
            raise
        finally:
            PhaseService.close_door(db)
        return {"closed": cerro, "version": numero}

    @staticmethod
    def would_close(db: Session, process, user_id: int) -> bool:
        """¿La aprobación de `user_id` cumpliría la regla? Para que la UI ponga
        la reconfirmación (D6) en su formulario; el servidor la exige igual.
        Cualquier negativa (no vota, cerrada, sin versión, regla desconocida,
        fuera del corte) es False."""
        try:
            ReviewService._assert_operable(db)
            st = ReviewService._vote_state(db, process, user_id, fresh=False)
        except ValueError:
            return False
        return ReviewService._satisfied(
            st["roles"], {**st["verdicts"], st["assignment"].role: "approved"})

    @staticmethod
    def rule_satisfied(db: Session, process) -> bool:
        """Todos los roles que cuentan, con asignación VIGENTE, tienen
        `approved` en la versión vigente. Es lo que respalda la puerta del
        motor (`PhaseService._door_state_ok`). Regla desconocida o sin versión:
        False."""
        try:
            roles = ReviewService.counting_roles(ReviewService.rule_for(process))
        except ValueError:
            return False
        version = ReviewService.current_version(db, process.id)
        if version is None:
            return False
        filas = ReviewService._active_verdicts(db, process.id, version.id)
        return ReviewService._satisfied(roles, {role: v for role, _u, v in filas})

    # ------------------------------------------------------------------
    # Estado (§8.3): para el panel y para quien no está en la conversación
    # ------------------------------------------------------------------
    @staticmethod
    def status_for_process(db: Session, process_id: int, *,
                           holidays: frozenset[date] | None = None) -> dict | None:
        """Estado de la revisión SIN mensajes ni archivos, o None si el proceso
        no tiene conversación.

        `version`, `uploaded_at`/`uploaded_label`, `due`/`due_label`,
        `semaphore` (`ok|warn|late`; None sin versión, con la revisión cerrada
        o el proceso fuera de `active`: ahí no corre plazo), `votes` (una fila
        por asignación vigente en el orden del oficio: `role`, `role_label`,
        `name`, `counts`, `verdict` en la versión vigente), `rule_label`,
        `approvals`/`required` (votos que cuentan aprobados / necesarios),
        `closed`/`closed_at`. El calendario se lee una vez si no lo pasan.
        """
        from itcj2.apps.titulatec.models import (
            ReviewVote,
            SynodalAssignment,
            TitulationProcess,
        )
        from itcj2.apps.titulatec.utils.dates_es import dia_largo, dia_mes_hora
        from itcj2.core.models.user import User

        chat = ReviewService._chat_of(db, process_id)
        if chat is None:
            return None
        process = db.get(TitulationProcess, process_id)
        rule = ReviewService.rule_for(process)
        try:
            roles = ReviewService.counting_roles(rule)
        except ValueError:
            roles = ()
        version = ReviewService.current_version(db, process_id)

        vid = version.id if version is not None else -1     # sin versión: ningún voto
        filas = (db.query(SynodalAssignment.role, User.first_name, User.last_name,
                          User.middle_name, ReviewVote.verdict)
                 .join(User, User.id == SynodalAssignment.user_id)
                 .outerjoin(ReviewVote, and_(ReviewVote.assignment_id == SynodalAssignment.id,
                                             ReviewVote.version_id == vid))
                 .filter(SynodalAssignment.process_id == process_id,
                         SynodalAssignment.is_active.is_(True)).all())
        orden = {r: i for i, r in enumerate(ROLES)}
        filas = sorted(filas, key=lambda f: orden.get(f.role, len(ROLES)))
        votos = [{
            "role": f.role,
            "role_label": ROLE_LABELS.get(f.role, f.role),
            "name": _name(f.first_name, f.last_name, f.middle_name),
            "counts": f.role in roles,
            "verdict": f.verdict,
        } for f in filas]

        closed = chat.closed_at is not None
        due = semaforo = None
        if version is not None:
            if holidays is None:
                from itcj2.apps.titulatec.services.non_working_day_service import (
                    NonWorkingDayService,
                )
                holidays = NonWorkingDayService.holidays(db)
            due = ReviewService.due_date(version, holidays=holidays)
            if not closed and process is not None and process.status == "active":
                semaforo = ReviewService.semaphore(due, today=db_now().date(),
                                                   holidays=holidays)
        return {
            "process_id": process_id,
            "version": version.number if version is not None else None,
            "uploaded_at": version.uploaded_at if version is not None else None,
            "uploaded_label": (dia_mes_hora(version.uploaded_at)
                               if version is not None and version.uploaded_at else ""),
            "due": due,
            "due_label": dia_largo(due) if due else "",
            "semaphore": semaforo,
            "votes": votos,
            "rule_label": ReviewService.rule_label(rule),
            "approvals": sum(1 for v in votos if v["counts"] and v["verdict"] == "approved"),
            "required": len(roles),
            "closed": closed,
            "closed_at": chat.closed_at,
        }

    # ------------------------------------------------------------------
    # Leídos (§7.1)
    # ------------------------------------------------------------------
    @staticmethod
    def mark_read(db: Session, chat_id: int, user_id: int, last_id: int) -> None:
        """Marca leído hasta `last_id` (upsert monótono: nunca retrocede).
        Commit."""
        from sqlalchemy.dialects.postgresql import insert

        from itcj2.apps.titulatec.models import ChatRead

        ultimo = _to_int(last_id)
        if not ultimo or ultimo <= 0:
            return
        tabla = ChatRead.__table__
        stmt = insert(tabla).values(chat_id=chat_id, user_id=user_id,
                                    last_read_message_id=ultimo, updated_at=db_now())
        stmt = stmt.on_conflict_do_update(
            index_elements=[tabla.c.chat_id, tabla.c.user_id],
            set_={"last_read_message_id": func.greatest(
                      tabla.c.last_read_message_id, stmt.excluded.last_read_message_id),
                  "updated_at": stmt.excluded.updated_at})
        db.execute(stmt)
        db.commit()

    @staticmethod
    def unread_counts(db: Session, user_id: int, chat_ids) -> dict[int, int]:
        """`{chat_id: mensajes sin leer}` (de otros o del sistema, posteriores a
        su última lectura), 0 para los que no tienen. Una consulta."""
        from itcj2.apps.titulatec.models import ChatMessage, ChatRead

        ids = sorted({int(c) for c in (chat_ids or ()) if c is not None})
        if not ids:
            return {}
        filas = (db.query(ChatMessage.chat_id, func.count(ChatMessage.id))
                 .outerjoin(ChatRead, and_(ChatRead.chat_id == ChatMessage.chat_id,
                                           ChatRead.user_id == user_id))
                 .filter(ChatMessage.chat_id.in_(ids),
                         ChatMessage.id > func.coalesce(ChatRead.last_read_message_id, 0),
                         or_(ChatMessage.author_id.is_(None),
                             ChatMessage.author_id != user_id))
                 .group_by(ChatMessage.chat_id).all())
        salida = {cid: 0 for cid in ids}
        salida.update({cid: int(n) for cid, n in filas})
        return salida

    # ------------------------------------------------------------------
    # Archivos (§7.2, §12)
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve(stored: str | None) -> Path | None:
        """Ruta absoluta anclada a la raíz de archivos, o None si escapa."""
        from itcj2.apps.titulatec.utils import storage
        from itcj2.core.utils.safe_paths import UnsafePath, is_within

        if not stored:
            return None
        p = Path(stored)
        if p.is_absolute():
            return p if is_within(storage._base(), p) else None
        try:
            return storage.safe_abs_path(stored)
        except UnsafePath:
            return None

    @staticmethod
    def attachment_for(db: Session, process_id: int, message_id: int) -> dict | None:
        """El archivo de un mensaje para descargarlo, o None.

        El mensaje se busca DENTRO de la conversación de `process_id` (el
        proceso que la ruta ya autorizó), nunca suelto. Un mensaje `version`
        sirve el archivo de su versión. Devuelve `path` (absoluta, anclada a la
        raíz de archivos y existente), `download_name` (saneado), `mime` (por
        la extensión real) y `disposition` (`inline` solo PDF)."""
        from itcj2.apps.titulatec.models import ChatMessage, ProcessChat, ReviewVersion
        from itcj2.apps.titulatec.utils import review_files

        mid = _to_int(message_id)
        if mid is None:
            return None
        msg = (db.query(ChatMessage)
               .join(ProcessChat, ProcessChat.id == ChatMessage.chat_id)
               .filter(ChatMessage.id == mid, ProcessChat.process_id == process_id)
               .first())
        if msg is None:
            return None
        if msg.kind == "version" and msg.version_id:
            version = db.get(ReviewVersion, msg.version_id)
            if version is None or version.process_id != process_id:
                return None
            stored, nombre = version.file_path, version.original_name
        elif msg.attachment_path:
            stored, nombre = msg.attachment_path, msg.attachment_name
        else:
            return None
        ext = os.path.splitext(stored or "")[1].lstrip(".").lower()
        if ext not in review_files.REVIEW_TYPES:
            return None
        path = ReviewService._resolve(stored)
        if path is None or not path.is_file():
            return None
        return {
            "path": path,
            "download_name": review_files.download_name(nombre, ext),
            "mime": review_files.REVIEW_TYPES[ext],
            "disposition": review_files.disposition(ext),
        }
