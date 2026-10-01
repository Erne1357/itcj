"""Encolado de los correos del proceso al egresado (spec 2026-09-28, §5 y §6 C2/C7).

Una función por evento del catálogo (§5) arma el payload con los hechos del
evento y llama al `enqueue` común, que deja una fila `pending` en
`titulatec_email_outbox` DENTRO de la transacción del service que origina el
evento. Aquí no se envía nada ni se resuelve a quién: eso lo hace el
despachador periódico (`titulatec.email_dispatch`), con `contact_email` al
momento de enviar.

CONTRATO DE `enqueue` (lo consumen los ganchos de los services y el barrido de
recordatorios):

- NO hace commit. Sin `dedupe_key` tampoco hace flush: solo `db.add(row)`. El
  service del evento es dueño de su transacción; si revierte, la fila nunca
  existió.
- Con `dedupe_key` (solo los cuatro recordatorios) ejecuta en el acto
  `INSERT … ON CONFLICT (dedupe_key) DO NOTHING RETURNING id` y devuelve si
  insertó: correr el barrido dos veces no duplica. Ese INSERT va dentro de un
  SAVEPOINT de la conexión (sin flush de la sesión): si Postgres lo rechaza se
  deshace solo él. Sin el SAVEPOINT, el error deja abortada la transacción
  ENTERA del llamador y su siguiente statement revienta, aunque aquí se haya
  devuelto `False`.
- NUNCA lanza (best-effort, como `notify.notify_student`): lo que no se puede
  encolar queda en el log como warning y la función devuelve `False`. Todo se
  valida ANTES de tocar la sesión (payload con `json.dumps`, `kind` del
  catálogo, largo de las llaves, proceso con id y alumno): una fila inválida
  agregada con `db.add` reventaría en el commit DEL LLAMADOR y tumbaría la
  acción que la originó.
- `TITULATEC_EMAIL_ENABLED = false` → `False` sin escribir nada.

El payload lleva solo hechos del evento, serializables (fechas en ISO; montos
como texto «1200.00», porque JSON no serializa `Decimal`): nunca NIP, token,
liga de activación ni contraseña (el correo del NIP no pasa por esta tabla,
D3). Se guarda una copia congelada (ida y vuelta por JSON), así que lo que el
llamador cambie después en su dict no llega a la fila.

LIGAS (D10, C7): `{PUBLIC_ORIGIN}/itcj/login?next=<ruta codificada>`. Con
sesión, el login redirige directo a `next`; sin sesión, entra y cae ahí. La
ruta tiene que pasar `safe_next` (el mismo validador del login) o `link`
levanta `ValueError`. El origen vive en un solo lugar:
`email_helper.PUBLIC_ORIGIN`.

Los settings se leen solo por `MailSettings`: las pruebas parchean esos
métodos, nunca `get_settings` (que vive en `lru_cache` por proceso).
"""
from __future__ import annotations

import functools
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from urllib.parse import quote

from sqlalchemy.orm import Session

from itcj2.core.utils.timezone import db_now

if TYPE_CHECKING:  # solo para las anotaciones: los modelos se importan dentro de cada función
    from itcj2.apps.titulatec.models.email_outbox import EmailOutbox

logger = logging.getLogger(__name__)

# Dominios de los parámetros por evento (spec §5).
_DOC_STATUSES = ("approved", "rejected")
_SURVEY_RESULTS = ("approved", "rejected", "revoked")
_APPT_EVENTS = ("scheduled", "rescheduled", "cancelled")
_APPT_ACTORS = ("officer", "student")
# No adeudo de biblioteca (spec 2026-10-01-titulatec-biblioteca-caja-design.md
# §4.2/§4.11): cómo quedó liberado (el `legacy` del backfill nunca es una
# transición, así que nunca llega aquí) y a qué estado regresa al revertir.
_LIBRARY_VIAS = ("payment", "no_charge", "prior")
_LIBRARY_REVERTED_TO = ("awaiting_payment", "pending")


def _settings():
    """`get_settings()` está cacheado; el import va local (gotcha 2 del CLAUDE.md raíz)."""
    from itcj2.config import get_settings

    return get_settings()


class MailSettings:
    """Única lectura de los `TITULATEC_EMAIL_*` / `TITULATEC_REMINDER_*` /
    `TITULATEC_APPT_REMINDER_DAYS_BEFORE` (spec C6). Cambiar cualquiera exige
    variable de entorno y reiniciar TODOS los procesos."""

    @staticmethod
    def enabled() -> bool:
        """Interruptor general: apagado, nada se encola (ni se despacha)."""
        return bool(_settings().TITULATEC_EMAIL_ENABLED)

    @staticmethod
    def digest_minutes() -> int:
        """Espera del agrupado (D7) y gracia de «no se presentó» (D8)."""
        return int(_settings().TITULATEC_EMAIL_DIGEST_MINUTES)

    @staticmethod
    def max_attempts() -> int:
        """Intentos de envío antes de marcar la fila `failed`."""
        return int(_settings().TITULATEC_EMAIL_MAX_ATTEMPTS)

    @staticmethod
    def first_days() -> int:
        """Días desde el ancla hasta el primer recordatorio (D6)."""
        return int(_settings().TITULATEC_REMINDER_FIRST_DAYS)

    @staticmethod
    def every_days() -> int:
        """Días entre recordatorios después del primero (D6)."""
        return int(_settings().TITULATEC_REMINDER_EVERY_DAYS)

    @staticmethod
    def max_reminders() -> int:
        """Tope de recordatorios por ancla; 0 = sin recordatorios de documentos/encuesta."""
        return int(_settings().TITULATEC_REMINDER_MAX)

    @staticmethod
    def appt_days_before() -> int:
        """Días antes de la cita para su recordatorio; 0 = sin recordatorio de cita."""
        return int(_settings().TITULATEC_APPT_REMINDER_DAYS_BEFORE)


def _pid(process):
    """Id del proceso para el log, sin arriesgar otra excepción al leerlo."""
    try:
        return process.id
    except Exception:
        return None


def _best_effort(fn):
    """Ningún correo tumba la acción que lo origina (spec C2): cualquier error
    queda como warning en el log y la función devuelve `False`."""
    @functools.wraps(fn)
    def _wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            process = kwargs.get("process", args[1] if len(args) > 1 else None)
            logger.warning("[titulatec] No se encoló el correo %s del proceso %s: %s",
                           kwargs.get("kind", fn.__name__), _pid(process), exc)
            return False
    return _wrapper


def _iso(value):
    """Fecha/hora a texto ISO para el payload; `None` pasa igual."""
    return value.isoformat() if value is not None else None


def _monto(value):
    """Monto a texto con centavos para el payload («1200.00»): JSON no
    serializa `Decimal`. Solo `Decimal` o `int` finitos (nunca `float`, `bool`
    ni texto, la regla del dinero de la app); `None` pasa igual. Otra cosa
    levanta y `_best_effort` lo vuelve `False`."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise ValueError(f"monto inválido: {value!r}")
    monto = Decimal(value)
    if not monto.is_finite():
        raise ValueError(f"monto inválido: {value!r}")
    return f"{monto:.2f}"


def _outbox_values(model, *, kind, process, payload, group_key, dedupe_key,
                   not_before, created_at=None) -> dict:
    """Valida TODO antes de tocar la sesión y arma las columnas de la fila.
    Cualquier problema levanta aquí (y `_best_effort` lo convierte en `False`),
    nunca en el flush del llamador."""
    from itcj2.apps.titulatec.models.email_outbox import OUTBOX_KINDS

    if kind not in OUTBOX_KINDS:
        raise ValueError(f"tipo de correo desconocido: {kind!r}")
    if not isinstance(payload, dict):
        raise ValueError("el payload debe ser un dict")
    # `allow_nan=False`: NaN/Infinity no son JSON y la columna los rechazaría.
    congelado = json.loads(json.dumps(payload, allow_nan=False))
    pid, uid = process.id, process.student_id
    if pid is None or uid is None:
        raise ValueError("el proceso no tiene id o alumno")
    columnas = model.__table__.c
    for nombre, valor in (("group_key", group_key), ("dedupe_key", dedupe_key)):
        if valor is not None and (not isinstance(valor, str) or not valor
                                  or len(valor) > columnas[nombre].type.length):
            raise ValueError(f"{nombre} inválida: {valor!r}")
    for nombre, valor in (("not_before", not_before), ("created_at", created_at)):
        if valor is not None and not isinstance(valor, datetime):
            raise ValueError(f"{nombre} debe ser datetime")

    values = {"kind": kind, "process_id": pid, "user_id": uid,
              "group_key": group_key, "dedupe_key": dedupe_key, "payload": congelado}
    if not_before is not None:           # si no, el server_default NOW()
        values["not_before"] = not_before
    if created_at is not None:           # ídem
        values["created_at"] = created_at
    return values


class StudentMail:
    """Correos del proceso al egresado: encola, resuelve destinatario y arma ligas."""

    # Nombre de cada tipo en voz de ventanilla: la bitácora del expediente lo
    # enseña mientras la fila no tiene asunto (aún no sale, o nunca salió).
    KIND_LABELS = {
        "docs_review": "Dictamen de documentos",
        "phase_approved": "Fase aprobada",
        "phase_rejected": "Fase rechazada",
        "survey_approved": "GTV liberó la encuesta",
        "survey_rejected": "GTV dejó observaciones",
        "survey_revoked": "Se revocó la liberación de la encuesta",
        "appt_changed": "Aviso de cita de cotejo",
        "appt_reminder": "Recordatorio de cita de cotejo",
        "appt_no_show": "Aviso de inasistencia a la cita",
        "docs_reminder": "Recordatorio de documentos",
        "survey_reminder": "Recordatorio de encuesta de egresados",
        "library_ready": "Biblioteca lo pasó a Caja",
        "library_cleared": "Se liberó el no adeudo de biblioteca",
        "library_reverted": "Se revirtió el no adeudo de biblioteca",
        "library_reminder": "Recordatorio de pago en Caja",
    }

    # ------------------------------------------------------------------
    # Grupos (D7) y ligas (D10)
    # ------------------------------------------------------------------
    @staticmethod
    def docs_group(process_id: int) -> str:
        """Dictámenes de documentos y el avance de la fase `initial_docs`."""
        return f"docs:{process_id}"

    @staticmethod
    def appt_group(process_id: int) -> str:
        """Agendar / mover / cancelar la cita de cotejo."""
        return f"cita:{process_id}"

    @staticmethod
    def link(path: str) -> str:
        """Liga absoluta al login con `next` = `path` codificado entero.

        `path` es una ruta RELATIVA del sitio que `safe_next` acepta tal cual:
        empieza con UNA `/` (ni `//host` ni `/\\host`), sin esquema, sin
        espacios a los lados ni caracteres de control. Si no, `ValueError`.
        """
        from itcj2.apps.titulatec.services.email_helper import PUBLIC_ORIGIN
        from itcj2.core.pages.auth import safe_next

        if not isinstance(path, str) or safe_next(path) != path:
            raise ValueError(f"la liga solo acepta rutas relativas del sitio: {path!r}")
        return f"{PUBLIC_ORIGIN}/itcj/login?next={quote(path, safe='')}"

    # ------------------------------------------------------------------
    # Destinatario (D2) y bitácora
    # ------------------------------------------------------------------
    @staticmethod
    def contact_email(db: Session, process) -> str | None:
        """Correo PERSONAL del egresado, o `None` si no hay (la fila quedará
        `no_recipient`).

        `core_student_profile.contact_email` → respaldo: el `contact_email` de la
        `EnrollmentRequest` más reciente que convirtió ESTE proceso → `None`.
        Vacío o solo espacios cuenta como ausente. Nunca el institucional. Solo
        lectura: no crea el perfil si no existe.
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest
        from itcj2.core.models.student_profile import StudentProfile

        perfil = db.get(StudentProfile, process.student_id)
        correo = ((perfil.contact_email or "").strip() if perfil is not None else "")
        if correo:
            return correo
        fila = (db.query(EnrollmentRequest.contact_email)
                .filter(EnrollmentRequest.converted_process_id == process.id)
                .order_by(EnrollmentRequest.id.desc())
                .first())
        correo = (fila[0] or "").strip() if fila is not None else ""
        return correo or None

    @staticmethod
    def history(db: Session, process_id: int, limit: int = 100) -> list[EmailOutbox]:
        """Filas del outbox del proceso, las más nuevas primero (`created_at`
        DESC; `id` desempata las de una misma transacción, que comparten NOW())."""
        from itcj2.apps.titulatec.models import EmailOutbox

        return (db.query(EmailOutbox)
                .filter(EmailOutbox.process_id == process_id)
                .order_by(EmailOutbox.created_at.desc(), EmailOutbox.id.desc())
                .limit(limit)
                .all())

    # ------------------------------------------------------------------
    # Encolar
    # ------------------------------------------------------------------
    @staticmethod
    @_best_effort
    def enqueue(db: Session, *, kind: str, process, payload: dict,
                group_key: str | None = None, dedupe_key: str | None = None,
                not_before: datetime | None = None,
                created_at: datetime | None = None) -> bool:
        """Deja el correo `kind` pendiente para el alumno del proceso
        (`user_id = process.student_id`). `True` = quedó en la transacción del
        llamador. `not_before`/`created_at` en `None` = el `NOW()` de la BD;
        `created_at` explícito solo lo usan los recordatorios de cadencia (el
        reloj del barrido, ver `_reminder`). Contrato completo en el docstring
        del módulo."""
        if not MailSettings.enabled():
            return False
        from itcj2.apps.titulatec.models import EmailOutbox

        values = _outbox_values(EmailOutbox, kind=kind, process=process,
                                payload=payload, group_key=group_key,
                                dedupe_key=dedupe_key, not_before=not_before,
                                created_at=created_at)
        if dedupe_key is None:
            db.add(EmailOutbox(**values))
            return True

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        tabla = EmailOutbox.__table__
        stmt = (pg_insert(tabla).values(**values)
                .on_conflict_do_nothing(index_elements=["dedupe_key"])
                .returning(tabla.c.id))
        conn = db.connection()
        with conn.begin_nested():
            return conn.execute(stmt).first() is not None

    # ------------------------------------------------------------------
    # Un correo por evento del catálogo (spec §5). True = quedó encolado.
    # ------------------------------------------------------------------
    @staticmethod
    @_best_effort
    def doc_reviewed(db: Session, process, *, type_code: str, doc_name: str,
                     status: str, note: str | None) -> bool:
        """Dictamen de UN documento (#1). Va al grupo `docs:{pid}`: sale junto con
        los demás dictámenes cuando el grupo lleva la espera sin movimiento.
        `note` es el motivo tal como estaba al dictaminar."""
        if status not in _DOC_STATUSES:
            raise ValueError(f"dictamen de documento desconocido: {status!r}")
        return StudentMail.enqueue(
            db, kind="docs_review", process=process,
            payload={"type_code": type_code, "name": doc_name, "status": status,
                     "note": note},
            group_key=StudentMail.docs_group(process.id))

    @staticmethod
    @_best_effort
    def phase_approved(db: Session, process, *, phase_number: int, phase_name: str,
                       next_phase: int | None, next_name: str | None,
                       handoff: bool) -> bool:
        """Fase aprobada (#1b/#2). La fase `initial_docs` del catálogo va al grupo
        `docs:{pid}` (su aviso sale en el mismo correo que el dictamen de sus
        documentos); cualquier otra —o sin catálogo— sale sola.
        `completed` = no hay fase siguiente."""
        from itcj2.apps.titulatec.services.phase_service import PhaseService

        inicial = PhaseService.phase_number_for_code(db, "initial_docs")
        grupo = (StudentMail.docs_group(process.id)
                 if inicial is not None and phase_number == inicial else None)
        return StudentMail.enqueue(
            db, kind="phase_approved", process=process,
            payload={"phase_number": phase_number, "phase_name": phase_name,
                     "next_phase": next_phase, "next_name": next_name,
                     "handoff": handoff, "completed": next_phase is None},
            group_key=grupo)

    @staticmethod
    @_best_effort
    def phase_rejected(db: Session, process, *, phase_number: int, phase_name: str,
                       reason: str | None) -> bool:
        """Fase rechazada con su motivo (#3). Individual."""
        return StudentMail.enqueue(
            db, kind="phase_rejected", process=process,
            payload={"phase_number": phase_number, "phase_name": phase_name,
                     "reason": reason})

    @staticmethod
    @_best_effort
    def survey_result(db: Session, process, *, result: str,
                      reason: str | None = None,
                      origin: str = "submission") -> bool:
        """Dictamen sobre la encuesta (#4-#6): `result` ∈
        approved|rejected|revoked → `survey_{result}`. Individual.

        `origin` (D9, spec `2026-10-01-titulatec-biblioteca-caja-design.md`
        §4.11/§4.12) viaja en el payload junto con `reason`:
        `SurveyReviewService.register_prior` llama con
        `result="approved", origin="prior"` -el egresado no envió una
        encuesta real, trae su constancia del semestre anterior- y
        `survey_result.html` cambia el texto del resultado "approved" para
        ese caso. `approve`/`reject`/`revoke` nunca lo pasan: se quedan en
        el valor por omisión `"submission"`, el de siempre.
        """
        from itcj2.apps.titulatec.models.survey_review import SURVEY_REVIEW_ORIGINS

        if result not in _SURVEY_RESULTS:
            raise ValueError(f"resultado de GTV desconocido: {result!r}")
        if origin not in SURVEY_REVIEW_ORIGINS:
            raise ValueError(f"origen de encuesta desconocido: {origin!r}")
        return StudentMail.enqueue(
            db, kind=f"survey_{result}", process=process,
            payload={"reason": reason, "origin": origin})

    @staticmethod
    @_best_effort
    def appointment_changed(db: Session, process, *, event: str, appt, by: str,
                            reason: str | None = None) -> bool:
        """Cita agendada / movida / cancelada (#7), grupo `cita:{pid}`. El correo
        se arma al ENVIAR con la cita vigente; el payload guarda el evento, quién
        lo hizo (`officer`|`student`) y la cita tal como quedó."""
        if event not in _APPT_EVENTS:
            raise ValueError(f"evento de cita desconocido: {event!r}")
        if by not in _APPT_ACTORS:
            raise ValueError(f"actor de cita desconocido: {by!r}")
        return StudentMail.enqueue(
            db, kind="appt_changed", process=process,
            payload={"event": event, "by": by, "reason": reason, "appt_id": appt.id,
                     "scheduled_at": _iso(appt.scheduled_at),
                     "location": appt.location},
            group_key=StudentMail.appt_group(process.id))

    @staticmethod
    @_best_effort
    def appointment_no_show(db: Session, process, *, appt) -> bool:
        """«No se presentó» (#9). Espera la ventana del agrupado (D8): si el
        encargado lo deshace dentro de ella, el despachador lo da por obsoleto."""
        return StudentMail.enqueue(
            db, kind="appt_no_show", process=process,
            payload={"appt_id": appt.id, "scheduled_at": _iso(appt.scheduled_at)},
            not_before=db_now() + timedelta(minutes=MailSettings.digest_minutes()))

    @staticmethod
    @_best_effort
    def appointment_reminder(db: Session, process, *, appt) -> bool:
        """Recordatorio de la cita (#8): una vez por cita (`appt_reminder:{id}`)."""
        if appt.id is None:
            raise ValueError("la cita no tiene id")
        return StudentMail.enqueue(
            db, kind="appt_reminder", process=process,
            payload={"appt_id": appt.id, "scheduled_at": _iso(appt.scheduled_at),
                     "location": appt.location},
            dedupe_key=f"appt_reminder:{appt.id}")

    # ---- No adeudo de biblioteca (spec 2026-10-01-titulatec-biblioteca-caja-
    # design.md §4.11). Los encola `LibraryClearanceService` junto al aviso
    # in-app de cada transición, antes de su único commit. Individuales.
    @staticmethod
    @_best_effort
    def library_ready(db: Session, process, *, debt, donation, total,
                      note: str | None, updated: bool) -> bool:
        """Pasa a Caja (`library_debt_registered`) o Biblioteca corrigió el
        monto (`library_amount_corrected`, `updated=True`). Los montos van como
        texto «1200.00» y la nota tal como quedó; al ENVIAR el correo se
        re-valida (sigue `awaiting_payment`) y pinta los montos VIGENTES de la
        fila, no estos."""
        return StudentMail.enqueue(
            db, kind="library_ready", process=process,
            payload={"debt": _monto(debt), "donation": _monto(donation),
                     "total": _monto(total), "note": note, "updated": bool(updated)})

    @staticmethod
    @_best_effort
    def library_cleared(db: Session, process, *, via: str) -> bool:
        """El no adeudo quedó liberado: `via` ∈ payment (Caja cobró) |
        no_charge (total $0, D18) | prior (constancia previa, D9). El correo
        dice, con el estado VIVO, si ya puede agendar o qué le falta (D11)."""
        if via not in _LIBRARY_VIAS:
            raise ValueError(f"vía de liberación desconocida: {via!r}")
        return StudentMail.enqueue(db, kind="library_cleared", process=process,
                                   payload={"via": via})

    @staticmethod
    @_best_effort
    def library_reverted(db: Session, process, *, reason: str | None,
                         to_status: str) -> bool:
        """Se revirtió o deshizo la liberación, con su motivo: `to_status` es
        a dónde regresó (`awaiting_payment` = Caja revirtió el pago;
        `pending` = Biblioteca lo vuelve a revisar). Decide el «qué sigue»."""
        if to_status not in _LIBRARY_REVERTED_TO:
            raise ValueError(f"estado de reversión desconocido: {to_status!r}")
        return StudentMail.enqueue(db, kind="library_reverted", process=process,
                                   payload={"reason": reason, "to_status": to_status})

    @staticmethod
    @_best_effort
    def docs_reminder(db: Session, process, *, anchor: datetime, index: int,
                      created_at: datetime | None = None) -> bool:
        """Recordatorio de documentos (#10): el `index`-ésimo de esa ancla."""
        return StudentMail._reminder(db, "docs_reminder", process, anchor, index,
                                     created_at)

    @staticmethod
    @_best_effort
    def survey_reminder(db: Session, process, *, anchor: datetime, index: int,
                        created_at: datetime | None = None) -> bool:
        """Recordatorio de la encuesta de egresados (#11): el `index`-ésimo de esa ancla."""
        return StudentMail._reminder(db, "survey_reminder", process, anchor, index,
                                     created_at)

    @staticmethod
    @_best_effort
    def library_reminder(db: Session, process, *, anchor: datetime, index: int,
                         created_at: datetime | None = None) -> bool:
        """Recordatorio del pago pendiente en Caja (spec 2026-10-01 §4.11,
        D14): el `index`-ésimo de esa ancla (`ready_at`, la entrada VIGENTE a
        Caja)."""
        return StudentMail._reminder(db, "library_reminder", process, anchor, index,
                                     created_at)

    @staticmethod
    def _reminder(db: Session, kind: str, process, anchor: datetime, index: int,
                  created_at: datetime | None) -> bool:
        """Llave `{kind}:{pid}:{ancla}:{n}`: el barrido la recalcula igual en cada
        corrida, así que correrlo dos veces no duplica.

        `created_at` = el reloj del barrido que lo encola (`now` de
        `MailReminders.run`). La cadencia del ruling 19 mide la separación con
        el recordatorio anterior de la MISMA ancla por su `created_at`, así que
        tiene que salir del mismo reloj con el que después se compara."""
        return StudentMail.enqueue(
            db, kind=kind, process=process,
            payload={"anchor": anchor.isoformat(), "index": index},
            dedupe_key=f"{kind}:{process.id}:{anchor:%Y%m%dT%H%M%S}:{index}",
            created_at=created_at)
