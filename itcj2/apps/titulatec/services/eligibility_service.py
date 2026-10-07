"""Elegibilidad automática de las solicitudes de inscripción contra el SII.

Spec 2026-09-25 §3.4. Solo actúa en el modo `sii`
(`EnrollmentRequestService.reviewer_mode()`); en los otros dos modos todo
aquí es un no-op.

    alta pública ─commit─► enqueue_check(req_id)   (celery, best-effort)
                                 │
                   EligibilityService.check(db, req_id)
                                 │
       ① lock de la solicitud → ¿tiene cuenta? → fila `pending` (vigente) → COMMIT
       ② SII + reglas SIN lock tomado (puede tardar: timeouts del conector);
          sin cuenta y sin `error`, también el NIP → `classify_sii_nip`
       ③ lock + refresh → persiste apt | not_apt | error + nip_status → COMMIT

SII NO CONFIGURADO (spec 2026-09-27 D11: `TITULATEC_SII_BACKEND=disabled`, el
caso de producción mientras no haya acceso al SII). No hay a quién preguntar:
`check` no consulta, `enqueue_check` no publica y `sweep`/`recheck_errors` no
tocan la BD (devuelven sus conteos en cero con `"disabled": True`). La bandeja
aprueba «pasando a Accesos». Al configurarlo (y reiniciar), el barrido toma
toda solicitud por revisar sin consulta vigente como su primera consulta.
Único criterio: `EligibilityService.sii_configured()`.

CONCURRENCIA (Review Focus 2 y 3). La tarea puede correr antes de que el alta
sea visible (→ `None`, la recoge el barrido) y dos tareas del mismo `req_id`
pueden coincidir. Lo que evita duplicar la consulta es el lock + el estado de
la consulta VIGENTE (`last_check_id`):

- una vigente `pending` y fresca (`_PENDING_STALE`) significa que otro la está
  consultando: no se consulta otra vez, ni con `force`;
- sin `force`, el intento `attempt` ya hecho (o uno posterior) no se repite;
  eso vuelve idempotentes al reintento de celery y al barrido que coinciden;
- sin `force`, nunca se pasa de `max_attempts()`.

REINTENTOS (spec §3.4). Solo se reintenta el `error` con `retryable`: el SII
no respondió (`SiiUnavailable`). Lo reintentan la tarea de celery (con
backoff) y el barrido, hasta `max_attempts()`. Un error de configuración
(reglas rotas, consulta inválida, falla inesperada) queda como «Error» con su
motivo para Servicios Escolares.

`force=True` es «Reintentar consulta» de la bandeja: pregunta otra vez aunque
ya haya veredicto (el SII pudo cambiar), con el siguiente número de intento.

SE APRUEBA SIEMPRE (spec 2026-09-27 «el SII informa, Servicios Escolares
decide», §A3). La consulta NO aprueba nada: deja el veredicto, las reglas y las
diferencias de identidad para la bandeja de Solicitudes, y Servicios Escolares
da siempre el paso final (`EnrollmentRequestService.approve_detailed`, el único
que llama al núcleo `_approve_locked`; lo fija una prueba estructural). La
aprobación automática, su interruptor por convocatoria, la ventana de veto y la
edad máxima del veredicto se retiraron (D2).

ESTADO DEL NIP (spec 2026-09-27 §A2, D6). Sin cuenta, la consulta pregunta
también por el NIP del SII para que la bandeja pinte desde el inicio «Aprobar
y dar acceso» o «Aprobar y pasar a Accesos». Se guarda SOLO el estado
(`EligibilityCheck.nip_status`, dominio `NIP_STATUSES`), que decide UNA
función, `classify_sii_nip` (la usan también `sii-check` y la aprobación). El
`Secret` se revela ahí únicamente para `nip_format_ok` y se descarta en la
misma línea en que se pidió: nunca llega a un atributo, log, `facts`,
`results` ni payload. `RuleSet.evaluate` no corre la consulta de
`[credential]`, y los `facts`/`results` son la lista blanca de las reglas. Un
error que no es del SII se registra solo por su TIPO (su texto puede traer
cualquier cosa: la cadena de conexión, datos de la fila). Si AL APROBAR el SII
ya no da un NIP válido, la aprobación no escribe nada de la solicitud y
`record_nip_status` deja en la consulta vigente lo que vio (la fila pasa a
ofrecer Accesos).

Los settings del SII de este servicio se leen SOLO por `max_attempts()` (los
tests parchean ese método, nunca `get_settings`).
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

# Nombre de la tarea celery por solicitud (spec §3.4; `name=` en
# `itcj2/tasks/titulatec_tasks.py`). `enqueue_check` la manda por NOMBRE: el
# proceso web no importa el módulo de tareas.
CHECK_TASK_NAME = "titulatec.sii_check_request"

# Una consulta `pending` más vieja que esto se da por muerta (el worker cayó a
# media consulta) y se puede retomar. Holgado frente a los timeouts del
# conector (conexión ≤ 60 s + consulta ≤ 120 s, por cada `[[query]]`).
_PENDING_STALE = timedelta(minutes=15)

# Solicitudes por pasada del barrido (el resto, en la siguiente).
_SWEEP_BATCH = 200

# `falla` de `fetch_sii_nip` (el nombre del tipo de su error) que
# `EligibilityService.classify_sii_nip` traduce a `NIP_STATUSES`:
# `NIP_UNAVAILABLE` = el SII no respondió; `NIP_MISSING` (o `None`) = respondió
# sin NIP.
NIP_MISSING = "missing"
NIP_UNAVAILABLE = "SiiUnavailable"

# Dominio de `EligibilityCheck.nip_status` (spec 2026-09-27 §A2). Los cinco
# primeros los da `EligibilityService.classify_sii_nip` (sin cuenta);
# `not_needed` = tenía cuenta al consultar (no se pidió). NULL = no se revisó.
NIP_STATUSES = ("available", "missing", "invalid", "unavailable", "error", "not_needed")

# Campos de `[identity]` que se comparan con lo que se tecleó en el formulario.
_NAME_FIELDS = ("first_name", "last_name", "middle_name")
_NAME_LABELS = {"first_name": "nombre", "last_name": "apellido paterno",
                "middle_name": "apellido materno"}
# El nombre tecleado no es el del SII (hallazgo I1). `{campos}` = etiquetas de
# `_NAME_LABELS`, nunca los valores.
_NOTE_IDENTITY_MISMATCH = ("El nombre del formulario no coincide con el del SII ({campos}); "
                           "confirma que la solicitud sea de esa persona antes de aprobarla.")
# Campos que TIENEN que compararse (con valor en los dos lados) para dar la
# identidad por confirmada (revisión final C3/C9). El apellido materno es
# opcional.
_REQUIRED_NAME_FIELDS = ("first_name", "last_name")
# Clave de `identity_mismatch` con los campos obligatorios que NO se pudieron
# comparar (vacíos en el SII o en el formulario, o columna mal escrita).
_UNVERIFIED = "_unverified"
# Sin comparación del nombre la identidad no está confirmada: falla cerrado.
_NOTE_IDENTITY_UNVERIFIED = "No se pudo comparar el nombre con el SII."


def _norm(value) -> str:
    """Texto comparable: sin acentos, sin mayúsculas, espacios colapsados."""
    raw = unicodedata.normalize("NFKD", str(value or ""))
    sin_acentos = "".join(c for c in raw if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_acentos).strip().casefold()


def _identity_mismatch(db: Session, req, identity: dict) -> dict | None:
    """Diferencias formulario ↔ SII (spec §3.3).

    `None` = NO se comparó (sin `[identity]` o su consulta sin filas). `{}` =
    se comparó y coincide. Si no, `{campo: {form, sii}}` por diferencia y, en
    `_UNVERIFIED`, los campos de `_REQUIRED_NAME_FIELDS` que no se pudieron
    comparar por venir vacíos de algún lado (o por una columna de
    `[identity]` mal escrita, que el motor proyecta como NULL).

    Solo se compara lo que viene de los DOS lados: un apellido materno vacío
    en el formulario no es discrepancia. La carrera coincide si el texto del
    SII es el de la carrera elegida o el tecleado. No cambia el veredicto (ese
    es de las reglas); se muestra a Servicios Escolares, y una discrepancia de
    NOMBRE —o no haberlo podido comparar— la resume `identity_block`.
    """
    if not identity:
        return None
    out: dict = {}
    for campo in _NAME_FIELDS:
        form, sii = getattr(req, campo, None), identity.get(campo)
        if _norm(form) and _norm(sii) and _norm(form) != _norm(sii):
            out[campo] = {"form": form, "sii": sii}
    sin_comparar = [c for c in _REQUIRED_NAME_FIELDS
                    if not (_norm(getattr(req, c, None)) and _norm(identity.get(c)))]
    if sin_comparar:
        out[_UNVERIFIED] = sin_comparar

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
    return out


def _name_mismatch(chk) -> list[str]:
    """Etiquetas de los campos de NOMBRE en que el formulario y el SII difieren.

    Con alguno, la solicitud puede ser de OTRA persona (hallazgo I1): quien
    teclea el número de control de otra con su propio nombre dejaría creada la
    cuenta y el proceso de esa persona. La carrera NO cuenta (decisión): el SII
    suele nombrarla distinto que el catálogo (abreviada, con el plan) y se
    muestra a SE como diferencia, sin más.
    """
    diferencias = (chk.identity_mismatch or {}) if chk is not None else {}
    return [_NAME_LABELS[c] for c in _NAME_FIELDS if c in diferencias]


def identity_block(chk) -> str | None:
    """Por qué la IDENTIDAD de `chk` no está confirmada, o `None` si lo está.

    Falla cerrado (revisión final C3/C9): sin comparación del nombre
    (`identity_mismatch` NULL o con `_UNVERIFIED`) → `_NOTE_IDENTITY_UNVERIFIED`;
    nombre distinto al del SII → `_NOTE_IDENTITY_MISMATCH`. Alimenta la
    confirmación que la bandeja pide antes de aprobar (spec 2026-09-27 D7):
    Servicios Escolares aprueba igual, pero sabiendo que el nombre no coincide
    o no se pudo comparar.
    """
    im = chk.identity_mismatch if chk is not None else None
    if not isinstance(im, dict) or im.get(_UNVERIFIED):
        return _NOTE_IDENTITY_UNVERIFIED
    campos = _name_mismatch(chk)
    if campos:
        return _NOTE_IDENTITY_MISMATCH.format(campos=", ".join(campos))
    return None


def _lock(db: Session, req_id: int) -> None:
    """El MISMO lock por solicitud que `EnrollmentRequestService`."""
    from itcj2.apps.titulatec.services.enrollment_request_service import _REQUEST_LOCK_NS

    db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
               {"ns": _REQUEST_LOCK_NS, "key": int(req_id)})


def _transient_types() -> tuple:
    """Fallas que se arreglan esperando: el SII no respondió (`SiiUnavailable`)
    o celery cortó la tarea por tiempo (`SoftTimeLimitExceeded`: tiempo
    agotado, no configuración; revisión final)."""
    from itcj2.apps.titulatec.services.sii.errors import SiiUnavailable

    try:
        from celery.exceptions import SoftTimeLimitExceeded
    except ImportError:  # pragma: no cover - celery siempre está en el backend
        return (SiiUnavailable,)
    return (SiiUnavailable, SoftTimeLimitExceeded)


class _FailureWatch:
    """Envuelve al cliente del SII para saber de qué TIPO fue su falla.

    `RuleSet.evaluate` convierte cualquier falla del cliente en
    `Verdict(status="error")` sin decir de qué clase fue; esto la anota (solo
    la clase, nunca el mensaje) antes de dejarla subir, para distinguir el SII
    que no respondió (`SiiUnavailable`, se reintenta) de una consulta
    inválida (`SiiQueryError`, no).
    """

    def __init__(self, client):
        self._client = client
        self.failure: type[BaseException] | None = None

    def query(self, sql, params, **kwargs):
        try:
            return self._client.query(sql, params, **kwargs)
        except Exception as exc:
            self.failure = type(exc)
            raise


def _evaluate(control: str):
    """Pasos del SII, SIN tocar la BD. `(Verdict, retryable)`; nunca lanza.

    `retryable` (spec §3.4): el veredicto es `error` porque el SII no
    respondió (`SiiUnavailable`: conexión, timeout) o celery
    cortó la tarea por tiempo (`SoftTimeLimitExceeded`) — `_transient_types`.
    Reglas que no cargan o no se cumplen de forma evaluable, una consulta
    inválida o una falla inesperada son de configuración: `False`.
    """
    from itcj2.apps.titulatec.services.sii import client as sii_client
    from itcj2.apps.titulatec.services.sii.errors import SiiError
    from itcj2.apps.titulatec.services.sii.rules import RuleSet, Verdict

    transitorias = _transient_types()
    try:
        rules = RuleSet.load(sii_client.SiiConfig.rules_dir())
        with sii_client.get_sii_client() as client:
            watch = _FailureWatch(client)
            verdict = rules.evaluate(watch, control)
        retryable = (verdict.status == "error" and watch.failure is not None
                     and issubclass(watch.failure, transitorias))
        return verdict, retryable
    except SiiError as exc:
        # Mensajes ya saneados por contrato (sin cadena de conexión ni NIP).
        return (Verdict(status="error", error=str(exc) or type(exc).__name__),
                isinstance(exc, transitorias))
    except Exception as exc:  # noqa: BLE001 — la consulta nunca tumba la tarea
        logger.warning("SII: error inesperado al consultar la solicitud (%s)",
                       type(exc).__name__)
        return (Verdict(status="error",
                        error=f"Error inesperado al consultar el SII ({type(exc).__name__})."),
                isinstance(exc, transitorias))


def nip_failure(exc: BaseException) -> str:
    """La `falla` de `fetch_sii_nip` para `exc`: `NIP_UNAVAILABLE` si es
    transitoria (`_transient_types`), si no el NOMBRE de su tipo. La usa
    también `sii-check`, que pide el NIP por su cuenta para mostrar el motivo."""
    if isinstance(exc, _transient_types()):
        return NIP_UNAVAILABLE
    return type(exc).__name__


def fetch_sii_nip(control: str):
    """El NIP del SII de `control`: `(Secret | None, falla)`. Nunca lanza.

    `(Secret, None)`: el SII lo dio. `(None, None)`: el SII respondió pero no
    hay NIP (0 filas, NULL o vacío). `(None, "<Tipo>")`: no se pudo preguntar,
    y `falla` es el NOMBRE del tipo del error (`nip_failure`) —
    `NIP_UNAVAILABLE` (`SiiUnavailable`: caído, timeout, deshabilitado) es
    transitorio; cualquier otro (`SiiRulesError`, `SiiQueryError`, uno
    inesperado) es de configuración y esperar no lo arregla. El valor vive
    envuelto en `Secret` (repr `****`) hasta que quien lo recibe lo hashea o
    lo clasifica (`EligibilityService.classify_sii_nip`); aquí solo se
    registra el TIPO del error.

    Observabilidad (R1 del plan de rendimiento): la consulta se mide como
    `itcj_outbound_request_seconds{target="sii"}`. El `with` va DENTRO del `try`
    y envuelve solo la consulta: una falla del SII la clasifica (`error`, o
    `timeout`) y sigue su camino al `except` de siempre, que la vuelve `falla`.
    Quedan FUERA lo que no es una llamada saliente: leer las reglas del disco y
    pedir el cliente (con `TITULATEC_SII_BACKEND=disabled`, el caso de producción
    hoy, `get_sii_client()` lanza antes de cualquier petición); contarlos haría
    del panel una alarma permanente.
    """
    from itcj2.apps.titulatec.services.sii import client as sii_client
    from itcj2.apps.titulatec.services.sii.rules import RuleSet
    from itcj2.observability.work import measured_outbound

    try:
        rules = RuleSet.load(sii_client.SiiConfig.rules_dir())
        with sii_client.get_sii_client() as client:
            with measured_outbound("sii"):
                return rules.fetch_credential(client, control), None
    except Exception as exc:  # noqa: BLE001 — «no se pudo preguntar»
        logger.warning("SII: no se pudo consultar el NIP (%s)", type(exc).__name__)
        return None, nip_failure(exc)


def enqueue_check(req_id: int, *, attempt: int = 1, force: bool = False,
                  db=None) -> bool:
    """Encola la consulta de `req_id` en celery. Best-effort: NUNCA lanza.

    Devuelve si se encoló: «Reintentar consulta» no anuncia éxito si no
    (revisión final). Por nombre (`send_task`) y sin reintentar la publicación
    (`retry=False`): con el broker caído el alta no espera, y la solicitud sin
    consulta vigente la recoge el barrido periódico. Llamar SOLO después del
    commit.

    Con el SII sin configurar (D11) devuelve `False` SIN publicar: la tarea
    no tendría a quién preguntar. Al configurarlo, el barrido hace la primera
    consulta de lo que quedó pendiente.

    Con `force=True` y `db`, una consulta que SÍ se encoló deja en la bitácora
    `enrollment.sii_recheck_requested` (el actor sale del contexto de la
    petición) y se commitea en esa misma sesión; es best-effort como todo lo
    demás de aquí: un fallo al registrar no cambia el resultado. Sin `db` (el
    alta, el barrido) no se registra nada.
    """
    if not EligibilityService.sii_configured():
        return False
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
        return False
    if force and db is not None:
        _audit_recheck(db, req_id)
    return True


def _audit_recheck(db, req_id: int) -> None:
    """Bitácora de «Reintentar consulta». Nunca lanza."""
    try:
        from itcj2.apps.titulatec.models import EnrollmentRequest
        from itcj2.apps.titulatec.services.audit_service import AuditService
        from itcj2.apps.titulatec.services.enrollment_request_service import (
            _audit_subject,
        )

        req = db.get(EnrollmentRequest, int(req_id))
        AuditService.record(
            db, "enrollment.sii_recheck_requested",
            entity_type="enrollment_request", entity_id=int(req_id),
            subject=_audit_subject(req) if req is not None else None)
        db.commit()
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("No se pudo registrar la reconsulta de la solicitud %s (%s)",
                       req_id, type(exc).__name__)
        try:
            db.rollback()
        except Exception:      # pragma: no cover - sesión ya inservible
            pass


class EligibilityService:
    """Consulta de elegibilidad y barrido (modo `sii`). No aprueba nada."""

    @staticmethod
    def max_attempts() -> int:
        """Tope de intentos de consulta sin `force` (TITULATEC_SII_MAX_ATTEMPTS)."""
        from itcj2.config import get_settings

        return get_settings().TITULATEC_SII_MAX_ATTEMPTS

    @staticmethod
    def sii_configured() -> bool:
        """¿Hay SII a quién preguntar? `False` con el backend `disabled` (D11)."""
        from itcj2.apps.titulatec.services.sii.client import SiiConfig

        return SiiConfig.backend() != "disabled"

    @staticmethod
    def classify_sii_nip(secret, falla) -> str:
        """El estado del NIP del SII (`NIP_STATUSES`) para `(Secret | None, falla)`
        de `fetch_sii_nip` (en `check`, `sii-check` y `_approve_locked`). ÚNICA
        función que traduce.

        `secret` con formato válido → `available`; con otro formato →
        `invalid`; sin `secret` y sin falla (o `NIP_MISSING`) → `missing`;
        `NIP_UNAVAILABLE` → `unavailable`; cualquier otra falla → `error`. El
        formato es `nip_format_ok` (la regla del NIP vive solo ahí); el valor
        se revela solo para esa comparación y no se guarda.
        """
        from itcj2.apps.titulatec.services.enrollment_request_service import nip_format_ok

        if secret is not None:
            return "available" if nip_format_ok(secret.reveal()) else "invalid"
        if falla is None or falla == NIP_MISSING:
            return "missing"
        if falla == NIP_UNAVAILABLE:
            return "unavailable"
        return "error"

    @staticmethod
    def rules_version() -> str | None:
        """La `version` de las reglas vigentes, o `None` si no cargan."""
        from itcj2.apps.titulatec.services.sii import client as sii_client
        from itcj2.apps.titulatec.services.sii.errors import SiiError
        from itcj2.apps.titulatec.services.sii.rules import RuleSet

        try:
            return RuleSet.load(sii_client.SiiConfig.rules_dir()).version or None
        except SiiError:
            return None

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

        `None` = no se consultó: fuera del modo `sii`, con el SII sin
        configurar (D11; ni se lee la BD), la solicitud no existe (todavía), ya
        no está `pending_review`, otra consulta está en curso, o (sin `force`)
        ese intento ya se hizo o pasa del tope. Ver CONCURRENCIA en el módulo.

        `nip_status` (spec 2026-09-27 §A2): `not_needed` si el control tenía
        cuenta en ①; sin cuenta y con veredicto que no es `error`, el estado
        que da `classify_sii_nip` al NIP pedido en ②; `None` con veredicto
        `error` (no se llegó a preguntar). Un control que no cumple
        `CONTROL_NUMBER_RE` no se busca en `core_users` (mismo corte que
        `_sii_nip_unlocked`): cuenta como sin cuenta.
        """
        from itcj2.apps.titulatec.models import EligibilityCheck, EnrollmentRequest
        from itcj2.apps.titulatec.services.enrollment_request_service import (
            EnrollmentRequestService,
        )
        from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE
        from itcj2.core.models.user import User

        if EnrollmentRequestService.reviewer_mode() != "sii":
            return None
        if not EligibilityService.sii_configured():
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
        # Mismo criterio que la aprobación (`_sii_nip_unlocked`): `core_users`
        # ahora, y solo con un control de formato válido.
        tiene_cuenta = (CONTROL_NUMBER_RE.fullmatch(control) is not None
                        and db.query(User.id).filter_by(control_number=control)
                        .first() is not None)
        db.commit()          # suelta el lock: el SII puede tardar

        # ② El SII, sin lock ni transacción abierta.
        t0 = time.monotonic()
        verdict, retryable = _evaluate(control)
        if verdict.status == "error":
            nip_status = None            # no se llegó a preguntar
        elif tiene_cuenta:
            nip_status = "not_needed"    # con cuenta sale la liga, sin NIP
        else:
            # El `Secret` se clasifica y se descarta en esta misma línea.
            nip_status = EligibilityService.classify_sii_nip(*fetch_sii_nip(control))
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
        chk.retryable = retryable if verdict.status == "error" else None
        chk.identity_mismatch = _identity_mismatch(db, req, verdict.identity)
        chk.nip_status = nip_status
        chk.finished_at = datetime.now()
        chk.duration_ms = duration_ms
        db.commit()
        # Nada más: el veredicto queda para Servicios Escolares, que aprueba
        # siempre desde la bandeja (spec 2026-09-27 §A3).
        return chk

    @staticmethod
    def record_nip_status(db: Session, req_id: int, check_id: int | None,
                          status: str) -> bool:
        """Guarda en la consulta `check_id` el estado del NIP que vio la
        APROBACIÓN (`approve_detailed`, cuando el SII no dio un NIP válido):
        así la bandeja ya ofrece «pasar a Accesos». `True` si escribió.

        Solo si `check_id` sigue siendo la consulta VIGENTE de la solicitud
        (`last_check_id`) bajo el lock + `refresh`: una consulta más nueva no se
        pisa con lo que vio una aprobación anterior. `False` sin consulta
        (`None`) o con un `status` fuera de `NIP_STATUSES`. Transacción propia
        y corta: el llamador ya soltó la suya. Nunca lanza: registra solo el
        TIPO del error, `rollback` y `False`.
        """
        from itcj2.apps.titulatec.models import EligibilityCheck, EnrollmentRequest

        if check_id is None or status not in NIP_STATUSES:
            return False
        try:
            req = db.get(EnrollmentRequest, req_id)
            chk = None
            if req is not None:
                _lock(db, req.id)
                db.refresh(req)
                if req.last_check_id == check_id:
                    chk = db.get(EligibilityCheck, check_id, populate_existing=True)
            if chk is None:
                db.commit()      # cierra la transacción (y el lock) sin escribir
                return False
            chk.nip_status = status
            db.commit()
            return True
        except Exception as exc:  # noqa: BLE001 — un aviso, nunca tumba la aprobación
            try:
                db.rollback()
            except Exception:      # pragma: no cover - sesión ya inservible
                pass
            logger.warning("No se pudo guardar el estado del NIP de la solicitud %s (%s)",
                           req_id, type(exc).__name__)
            return False

    @staticmethod
    def recheck_errors(db: Session, *, cohort_id: int | None = None,
                       now: datetime | None = None) -> dict:
        """Reconsulta en bloque tras corregir la configuración. `{queued, failed}`
        (+ `"disabled"`).

        Encola una consulta FORZADA (`enqueue_check(id, force=True)`) para cada
        solicitud `pending_review` (de `cohort_id`, si se da) cuya consulta
        vigente es `error` —reintentable o no, en el tope o no— o `pending`
        colgada (`_PENDING_STALE`). El barrido no las toma: un error de
        configuración no se arregla esperando, y uno reintentable en el tope ya
        agotó sus intentos (revisión final C12). `failed` = no se pudo encolar
        (broker caído). Solo en el modo `sii`. No escribe en la BD: la fila
        `pending` la abre la tarea bajo el lock. Con el SII sin configurar
        (D11) no lee la BD y suma `"disabled": True`.
        """
        from sqlalchemy import and_, or_

        from itcj2.apps.titulatec.models import EligibilityCheck, EnrollmentRequest
        from itcj2.apps.titulatec.services.enrollment_request_service import (
            EnrollmentRequestService,
        )

        out = {"queued": 0, "failed": 0}
        if EnrollmentRequestService.reviewer_mode() != "sii":
            return out
        if not EligibilityService.sii_configured():
            return {**out, "disabled": True}
        now = now or datetime.now()
        EC, ER = EligibilityCheck, EnrollmentRequest
        q = (db.query(ER.id)
             .join(EC, EC.id == ER.last_check_id)
             .filter(ER.status == "pending_review")
             .filter(or_(EC.status == "error",
                         and_(EC.status == "pending",
                              EC.started_at < now - _PENDING_STALE))))
        if cohort_id:
            q = q.filter(ER.cohort_id == cohort_id)
        ids = [rid for (rid,) in q.order_by(ER.id).all()]
        db.commit()          # solo lectura: no deja la transacción abierta
        for rid in ids:
            out["queued" if enqueue_check(rid, force=True) else "failed"] += 1
        return out

    @staticmethod
    def sweep(db: Session, *, now: datetime | None = None, cohort_id: int | None = None,
              max_seconds: float | None = None) -> dict:
        """Barrido periódico. Devuelve `{"checked", "retried"}` (+ `"disabled"`).

        Solo CONSULTA, nunca aprueba (spec 2026-09-27 §A3: una apta queda para
        Servicios Escolares como cualquier otra). Sobre las solicitudes
        `pending_review` (de `cohort_id`, si se da):

        - sin consulta vigente (el worker o el broker no estaban) → primera
          consulta (`checked`);
        - vigente `error` REINTENTABLE (`retryable`: el SII no respondió;
          spec §3.4) con intentos por debajo de `max_attempts()` → siguiente
          intento (`retried`); `pending` colgada (`_PENDING_STALE`) → se
          retoma forzada, aunque esté en el tope (`retried`). Un error de
          configuración (reglas, consulta inválida) no se reintenta: esperar
          no lo arregla; tras corregirlo, `recheck_errors` (CLI
          `sii-sweep --reconsultar-errores`) o «Reintentar consulta».

        Cada solicitud va por separado: la que revienta se registra por su TIPO
        y no detiene a las demás. `max_seconds` es el presupuesto: no toma
        solicitudes nuevas pasado ese tiempo (la tarea termina antes de que
        celery la corte; lo que quedó lo toma el siguiente barrido). Lote de
        `_SWEEP_BATCH`.

        Con el SII sin configurar (D11) no lee la BD y suma `"disabled": True`;
        al configurarlo, lo que quedó sin consulta vigente entra aquí como
        primera consulta (no hace falta `--reconsultar-errores`).
        """
        from sqlalchemy import and_, or_

        from itcj2.apps.titulatec.models import EligibilityCheck, EnrollmentRequest
        from itcj2.apps.titulatec.services.enrollment_request_service import (
            EnrollmentRequestService,
        )

        out = {"checked": 0, "retried": 0}
        if EnrollmentRequestService.reviewer_mode() != "sii":
            return out
        if not EligibilityService.sii_configured():
            return {**out, "disabled": True}
        now = now or datetime.now()
        tope = EligibilityService.max_attempts()
        EC, ER = EligibilityCheck, EnrollmentRequest

        q = (db.query(ER.id, EC.status, EC.attempt)
             .outerjoin(EC, EC.id == ER.last_check_id)
             .filter(ER.status == "pending_review")
             .filter(or_(
                 ER.last_check_id.is_(None),
                 and_(EC.status == "error", EC.retryable.is_(True), EC.attempt < tope),
                 # Colgada, aunque esté en el tope (revisión final): nadie más
                 # la retoma; se fuerza abajo.
                 and_(EC.status == "pending", EC.started_at < now - _PENDING_STALE),
             )))
        if cohort_id:
            q = q.filter(ER.cohort_id == cohort_id)
        filas = q.order_by(ER.id).limit(_SWEEP_BATCH).all()
        db.commit()          # cierra la lectura: cada solicitud abre la suya

        t0 = time.monotonic()
        for req_id, status, attempt in filas:
            if max_seconds is not None and time.monotonic() - t0 >= max_seconds:
                break
            try:
                if status == "pending":
                    chk = EligibilityService.check(db, req_id, force=True)
                else:
                    chk = EligibilityService.check(
                        db, req_id, attempt=1 if status is None else attempt + 1)
                if chk is not None:
                    out["checked" if status is None else "retried"] += 1
            except Exception as exc:  # noqa: BLE001 — una no detiene a las demás
                db.rollback()
                logger.warning("SII: el barrido no pudo con la solicitud %s (%s)",
                               req_id, type(exc).__name__)
        return out
