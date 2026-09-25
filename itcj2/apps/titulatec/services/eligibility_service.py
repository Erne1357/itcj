"""Elegibilidad automática de las solicitudes de inscripción contra el SII.

Spec 2026-09-25 §3.4. Solo actúa en el modo `sii`
(`EnrollmentRequestService.reviewer_mode()`); en los otros dos modos todo
aquí es un no-op.

    alta pública ─commit─► enqueue_check(req_id)   (celery, best-effort)
                                 │
                   EligibilityService.check(db, req_id)
                                 │
       ① lock de la solicitud → fila `pending` (vigente) → COMMIT
       ② SII + reglas SIN lock tomado (puede tardar: timeouts del conector)
       ③ lock + refresh → persiste apt | not_apt | error → COMMIT

CONCURRENCIA (Review Focus 2 y 3). La tarea puede correr antes de que el alta
sea visible (→ `None`, la recoge el barrido) y dos tareas del mismo `req_id`
pueden coincidir. Lo que evita duplicar la consulta es el lock + el estado de
la consulta VIGENTE (`last_check_id`):

- una vigente `pending` y fresca (`_PENDING_STALE`) significa que otro la está
  consultando: no se consulta otra vez, ni con `force`;
- sin `force`, el intento `attempt` ya hecho (o uno posterior) no se repite;
  eso vuelve idempotentes al reintento de celery y al barrido que coinciden;
- sin `force`, nunca se pasa de `max_attempts()`.

`force=True` es «Reintentar consulta» de la bandeja: pregunta otra vez aunque
ya haya veredicto (el SII pudo cambiar), con el siguiente número de intento.

EL NIP DEL SII NO PASA POR AQUÍ al consultar: `RuleSet.evaluate` no corre la
consulta de `[credential]`, y los `facts`/`results` son la lista blanca de las
reglas. Un error que no es del SII se registra solo por su TIPO (su texto
puede traer cualquier cosa: la cadena de conexión, datos de la fila).

Los settings del SII de este servicio se leen SOLO por `delay_hours()` y
`max_attempts()` (los tests parchean esos métodos, nunca `get_settings`).
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("itcj2.apps.titulatec.eligibility")

# Nombre de la tarea celery por solicitud (`itcj2/tasks/titulatec_tasks.py`).
# `enqueue_check` la manda por NOMBRE: el proceso web no importa el módulo de
# tareas.
CHECK_TASK_NAME = "itcj2.tasks.titulatec_tasks.sii_check_request"

# Una consulta `pending` más vieja que esto se da por muerta (el worker cayó a
# media consulta) y se puede retomar. Holgado frente a los timeouts del
# conector (conexión ≤ 60 s + consulta ≤ 120 s, por cada `[[query]]`).
_PENDING_STALE = timedelta(minutes=15)

# Campos de `[identity]` que se comparan con lo que se tecleó en el formulario.
_NAME_FIELDS = ("first_name", "last_name", "middle_name")


def _norm(value) -> str:
    """Texto comparable: sin acentos, sin mayúsculas, espacios colapsados."""
    raw = unicodedata.normalize("NFKD", str(value or ""))
    sin_acentos = "".join(c for c in raw if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_acentos).strip().casefold()


def _identity_mismatch(db: Session, req, identity: dict) -> dict | None:
    """Diferencias formulario ↔ SII (spec §3.3). `None` si no hay ninguna.

    Solo se compara lo que viene de los DOS lados: un apellido materno vacío
    en el formulario no es discrepancia. La carrera coincide si el texto del
    SII es el de la carrera elegida o el tecleado. Informa a Servicios
    Escolares; no decide la aprobación (el riesgo del correo tecleado es el
    aceptado del spec §5).
    """
    out: dict = {}
    for campo in _NAME_FIELDS:
        form, sii = getattr(req, campo, None), identity.get(campo)
        if _norm(form) and _norm(sii) and _norm(form) != _norm(sii):
            out[campo] = {"form": form, "sii": sii}

    sii_program = identity.get("program")
    if _norm(sii_program):
        candidatos = [req.program_text]
        if req.program_id:
            from itcj2.core.models.program import Program
            program = db.get(Program, req.program_id)
            candidatos.append(getattr(program, "name", None))
        candidatos = [c for c in candidatos if _norm(c)]
        if candidatos and _norm(sii_program) not in {_norm(c) for c in candidatos}:
            out["program"] = {"form": candidatos[0], "sii": sii_program}
    return out or None


def _lock(db: Session, req_id: int) -> None:
    """El MISMO lock por solicitud que `EnrollmentRequestService`."""
    from itcj2.apps.titulatec.services.enrollment_request_service import _REQUEST_LOCK_NS

    db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
               {"ns": _REQUEST_LOCK_NS, "key": int(req_id)})


def _evaluate(control: str):
    """Pasos del SII, SIN tocar la BD. Devuelve un `Verdict`; nunca lanza."""
    from itcj2.apps.titulatec.services.sii import client as sii_client
    from itcj2.apps.titulatec.services.sii.errors import SiiError
    from itcj2.apps.titulatec.services.sii.rules import RuleSet, Verdict

    try:
        rules = RuleSet.load(sii_client.SiiConfig.rules_dir())
        with sii_client.get_sii_client() as client:
            return rules.evaluate(client, control)
    except SiiError as exc:
        # Mensajes ya saneados por contrato (sin cadena de conexión ni NIP).
        return Verdict(status="error", error=str(exc) or type(exc).__name__)
    except Exception as exc:  # noqa: BLE001 — la consulta nunca tumba la tarea
        logger.warning("SII: error inesperado al consultar la solicitud (%s)",
                       type(exc).__name__)
        return Verdict(status="error",
                       error=f"Error inesperado al consultar el SII ({type(exc).__name__}).")


def enqueue_check(req_id: int, *, attempt: int = 1, force: bool = False) -> None:
    """Encola la consulta de `req_id` en celery. Best-effort: NUNCA lanza.

    Por nombre (`send_task`) y sin reintentar la publicación (`retry=False`):
    con el broker caído el alta no espera, y la solicitud la recoge el barrido
    periódico (no tiene consulta vigente). Llamar SOLO después del commit.
    """
    try:
        from itcj2.celery_app import celery_app

        celery_app.send_task(
            CHECK_TASK_NAME,
            kwargs={"req_id": int(req_id), "attempt": int(attempt), "force": bool(force)},
            retry=False,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort
        # Solo el tipo: el texto de un error del broker puede traer su URL.
        logger.warning("No se pudo encolar la consulta al SII de la solicitud %s (%s)",
                       req_id, type(exc).__name__)


class EligibilityService:
    """Consulta de elegibilidad, aprobación automática y barrido (modo `sii`)."""

    @staticmethod
    def delay_hours() -> int:
        """Ventana de veto antes de aprobar sola (TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS)."""
        from itcj2.config import get_settings

        return get_settings().TITULATEC_SII_AUTO_APPROVE_DELAY_HOURS

    @staticmethod
    def max_attempts() -> int:
        """Tope de intentos de consulta sin `force` (TITULATEC_SII_MAX_ATTEMPTS)."""
        from itcj2.config import get_settings

        return get_settings().TITULATEC_SII_MAX_ATTEMPTS

    @staticmethod
    def latest_check(db: Session, req):
        """La consulta VIGENTE de la solicitud (`last_check_id`), o `None`."""
        from itcj2.apps.titulatec.models import EligibilityCheck

        if req is None or not req.last_check_id:
            return None
        return db.get(EligibilityCheck, req.last_check_id)

    @staticmethod
    def check(db: Session, req_id: int, *, attempt: int = 1, force: bool = False):
        """Consulta al SII para `req_id`. Devuelve la `EligibilityCheck` o `None`.

        `None` = no se consultó: fuera del modo `sii`, la solicitud no existe
        (todavía), ya no está `pending_review`, otra consulta está en curso, o
        (sin `force`) ese intento ya se hizo o pasa del tope. Ver CONCURRENCIA
        en el módulo.
        """
        from itcj2.apps.titulatec.models import EligibilityCheck, EnrollmentRequest
        from itcj2.apps.titulatec.services.enrollment_request_service import (
            EnrollmentRequestService,
        )

        if EnrollmentRequestService.reviewer_mode() != "sii":
            return None

        # ① Lock, decidir y abrir la fila `pending`, en una transacción corta.
        req = db.get(EnrollmentRequest, req_id)
        if req is None:
            return None
        _lock(db, req.id)
        db.refresh(req)
        if req.status != "pending_review":
            db.commit()
            return None
        vigente = EligibilityService.latest_check(db, req)
        now = datetime.now()
        if (vigente is not None and vigente.status == "pending"
                and vigente.started_at is not None
                and vigente.started_at > now - _PENDING_STALE):
            db.commit()
            return None
        if force:
            numero = (vigente.attempt + 1) if vigente is not None else 1
        else:
            numero = int(attempt)
            if ((vigente is not None and vigente.attempt >= numero)
                    or numero > EligibilityService.max_attempts()):
                db.commit()
                return None

        chk = EligibilityCheck(request_id=req.id, status="pending", attempt=numero,
                               started_at=now)
        db.add(chk)
        db.flush()
        req.last_check_id = chk.id
        control = (req.control_number or "").strip()
        db.commit()          # suelta el lock: el SII puede tardar

        # ② El SII, sin lock ni transacción abierta.
        t0 = time.monotonic()
        verdict = _evaluate(control)
        duration_ms = int((time.monotonic() - t0) * 1000)

        # ③ Re-lock + refresh para persistir.
        _lock(db, req.id)
        db.refresh(req)
        db.refresh(chk)
        chk.status = verdict.status
        chk.rules_version = verdict.rules_version or None
        chk.results = verdict.results_as_dicts() if verdict.results else None
        chk.facts = verdict.facts or None
        chk.error = verdict.error
        chk.identity_mismatch = (_identity_mismatch(db, req, verdict.identity)
                                 if verdict.identity else None)
        chk.finished_at = datetime.now()
        chk.duration_ms = duration_ms
        db.commit()
        return chk
