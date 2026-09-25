"""Solicitudes de auto-inscripción a una convocatoria de titulación.

FLUJO (2026-09-24; manda sobre el de 2026-09-15 y sobre §6.6-6.10 del diseño
original; spec `2026-09-24-titulatec-accesos-centro-computo-design.md` §3).
Toda solicitud pasa por una revisión y el acceso llega SOLO por correo. Quién
revisa lo decide `reviewer_mode()` (TITULATEC_ENROLLMENT_REVIEWER): en el modo
OFICIAL Servicios Escolares (SE) aprueba y Centro de Cómputo (CC) da el NIP; en
el ALTERNO, CC hace las dos cosas en un paso.

    create()                 ─► pending_review                          (sin correo)
    approve() [SE, oficial]  ─┬─ CON cuenta ─► approved                 liga al correo personal
                              └─ SIN cuenta ─► awaiting_access          SIN correo
    approve() [CC, alterno]  ─┬─ CON cuenta ─► approved                 liga
                              └─ SIN cuenta ─► converted                usuario + NIP (un paso)
    grant_access() [CC]      ─── awaiting_access ─┬─ SIN cuenta ─► converted  usuario + NIP
                                                  └─ CON cuenta (D10) ─► approved  liga
    return_to_review() [CC]  ─── awaiting_access ─► pending_review      return_note, sin correo
    verify() [liga]          ─── approved ─► converted | pending_review (review_note)
    reject() [SE | CC alt.]  ─── pending_review | awaiting_access | approved | legado
                                 ─► rejected                            (correo; la liga muere)

El alumno no se entera de `awaiting_access`: ni correo al aprobar ni al
devolver. `unverified` y `verified` son estados LEGADO del flujo con liga
previa: ya no se escriben, pero sus filas se pueden aprobar o rechazar.

"¿TIENE CUENTA?" SE DECIDE CONTRA `core_users` AL MOMENTO, nunca con `kind` (que
`create()` guarda solo para mostrar): al aprobar y OTRA VEZ al dar acceso (D10).
Si un CSV o un alta manual creó la cuenta entre SE y CC, «dar acceso» se desvía
a la liga y el NIP se ignora: crear otra cuenta chocaría con la real y el NIP
pisaría su contraseña.

RIESGO ACEPTADO Y SU CONTENCIÓN (invariante; sustituye a los rulings R5, B1 y
D17). La liga de una cuenta existente viaja al correo que TECLEÓ el solicitante:
quien escriba un número de control ajeno con su correo y pase la revisión puede
dejar inscrita a esa persona. Para que no escale:

  1. Sobre una cuenta que NO creó la solicitud JAMÁS se escribe
     `password_hash`, `must_change_password` ni `core_student_profile`, ni en
     `approve()`, ni en `grant_access()`, ni en `verify()`/`_convert()`. Lo
     único que recibe es el proceso y los roles de egresado (`graduate`, que
     desplaza a `student`; ver `ImportService.import_rows`).
     EXCEPCIÓN APROBADA (2026-09-15): abrir la liga pasa `is_active` de False a
     True. Sin eso la persona quedaba inscrita sin poder entrar. El riesgo es
     reactivar una cuenta que alguien desactivó a propósito, y se contiene así:
     solo lo hace la liga de una solicitud APROBADA (nunca `approve()`, que
     únicamente la emite); la bandeja pinta «Cuenta desactivada: se reactiva al
     abrir la liga» antes de aprobar; la contraseña no cambia, así que quien
     tecleó un control ajeno sigue sin poder entrar; el aviso con folio va al
     institucional (3), y el `ProcessEvent` registra `reactivated: true`.
  2. Una cuenta existente sin `password_hash` no recibe liga: se da de alta
     desde la convocatoria.
  3. El aviso con folio de `verify()` va al buzón INSTITUCIONAL de la cuenta:
     es la alarma de su dueña, y no depende de nada que se tecleó.
  4. No hay segunda liga. La de contacto canjeaba contra el perfil con la sola
     prueba del buzón tecleado: dejó de emitirse y el 2026-09-15 se retiró
     también su canje (`confirm_contact`, `GET /titulatec/inscripcion/correo` y
     la plantilla). Sus columnas quedan en la BD como legado sin uso.

Una cuenta NUEVA solo conoce su NIP por el correo que manda `_mail_access()`
(tras `grant_access` o el `approve` alterno). EL NIP NUNCA SALE de
otra forma: ni al log, ni al `detalle` que la ruta pone en `X-Tt-Error`, ni al
payload de un `ProcessEvent`. `access_sent_at` NULL con `access_granted_at`
lleno es «correo no enviado».

TOKEN (E7). La BD guarda SOLO `sha256(token)` y la comparación decisiva usa
`hmac.compare_digest`. El texto claro vive en Redis bajo `tt:enroll:tok:<sha256>`
lo mismo que la liga, y solo para que el reenvío PÚBLICO no rote: rotar desde un
endpoint anónimo dejaría a un extraño matar la liga de otra persona. Sin esa
copia el reenvío público falla CERRADO. La bandeja sí rota: su actor está
autenticado y acotado por carrera.

CORREO E INVALIDACIÓN DE AUTHZ SIEMPRE DESPUÉS DEL COMMIT. `msgraph_mail` es un
`requests.post` síncrono: dentro de la transacción retendría los advisory
locks, y un correo mandado antes de un commit que falla habla de algo que no
existe. Ningún método del helper lanza, así que un fallo de buzón no revierte
nada ya commiteado. El caché de authz, tirado antes del commit, lo repoblaría
una lectura concurrente con los roles de antes.

VENTANA (D5, spec 2026-09-24). `opens_at`/`closes_at` solo filtran el formulario
público (`CohortService.is_public_enrollment_open`, en la ruta). Todo lo que
sigue a una solicitud ya enviada —`approve`, `grant_access`, `verify`/`_convert`,
`resend_link` y `resend`— exige solo `status == 'open'`
(`CohortService.accepts_enrollment_followup`): una convocatoria `closed` pausa
sus procesos y tampoco emite ni canjea ligas, pero pasar `closes_at` no deja
varada a nadie que entró a tiempo. La liga vive `_link_ttl_hours()`.

CONCURRENCIA. Toda transición de una solicitud (`approve`, `grant_access`,
`return_to_review`, `verify`, `reject`, `resend_link`, `resend`) toma
`pg_advisory_xact_lock(_REQUEST_LOCK_NS, req.id)` y hace `db.refresh(req)`
ANTES de leer el estado: bajo READ COMMITTED, quien esperó el lock puede seguir
teniendo en memoria el estado de antes de esperarlo. Los tests estructurales de
cada método fijan ese orden.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE

logger = logging.getLogger("itcj2.apps.titulatec.enrollment_request")

STATUSES = ("unverified", "verified", "pending_review", "approved", "rejected", "converted",
            "awaiting_access")

# Desde dónde la bandeja aprueba (y rechaza, junto con `approved` y
# `awaiting_access`). `awaiting_access` NO es aprobable: SE ya la aprobó, y
# volver a aprobarla da su propio motivo (`_MSG_IN_ACCESS`).
_REVIEWABLE = ("pending_review", "unverified", "verified")
_REJECTABLE = _REVIEWABLE + ("approved", "awaiting_access")

# Agrupa los 7 STATUSES en los 5 cubos que pinta la bandeja (KPIs y "por año de
# ingreso", `EnrollmentRequestService.stats`): el legado `unverified`/`verified`
# cuenta como "por revisar", igual que en `_TAB_STATUSES` de `pages/requests_admin.py`.
_STATUS_GROUP = {s: "review" for s in _REVIEWABLE}
_STATUS_GROUP.update(awaiting_access="access", approved="sent", converted="converted",
                     rejected="rejected")

# Quién revisa en cada modo (`TITULATEC_ENROLLMENT_REVIEWER`); lo leen los textos
# públicos y los correos vía `EnrollmentRequestService.reviewer_label()`.
_REVIEWER_LABELS = {
    "school_services": "Servicios Escolares",
    "computer_center": "Centro de Cómputo",
}

# `control_number` -> año de ingreso, para el bloque "Por año de ingreso" de la
# bandeja. `CONTROL_NUMBER_RE` (import_service.py) ya exige `^[A-Za-z]?\d{8}$`;
# esto solo lee los 2 dígitos que siguen a la letra opcional, así que tolera un
# control legado o mal formado sin reventar (cae a "Sin año").
_ENTRY_YEAR_RE = re.compile(r"^[A-Za-z]?(\d{2})")


def entry_year(control: str | None, today: date | None = None) -> str:
    """Año de ingreso a 4 dígitos, o `"Sin año"` si el control no case (o es `None`).

    Pivote dinámico sobre los 2 últimos dígitos del año actual (o `today`,
    inyectable para test): `yy <= hoy % 100` -> `2000 + yy`; si no, `1900 + yy`.
    Ej. con hoy=2026: 26 -> 2026, 21 -> 2021, 90 -> 1990.
    """
    m = _ENTRY_YEAR_RE.match((control or "").strip())
    if not m:
        return "Sin año"
    yy = int(m.group(1))
    pivote = (today or date.today()).year % 100
    return str(2000 + yy if yy <= pivote else 1900 + yy)

# La vida de la liga NO es una constante: `EnrollmentRequestService._link_ttl_hours()`
# (TITULATEC_ENROLLMENT_LINK_TTL_DAYS, 21 días por omisión).
MAX_VERIFY_SENDS = 3             # tope del reenvío PÚBLICO; la bandeja no lo tiene
MIN_SECONDS_BETWEEN_SENDS = 300
MAX_PUBLIC_BODY_BYTES = 256 * 1024

# Mismo origen que `MaintEmailHelper._BASE_URL`: las ligas de correo salen de
# aquí, nunca del `Host` de la petición (que el cliente controla).
PUBLIC_BASE_URL = "https://enlinea.cdjuarez.tecnm.mx"

# Prefijo de Redis del TEXTO CLARO del token. La llave es el propio hash, así que
# una entrada rancia jamás puede aplicarse a otra solicitud.
_TOKEN_CACHE_PREFIX = "tt:enroll:tok:"

# Namespace del advisory lock POR SOLICITUD. Distinto de `_FOLIO_LOCK_NS`
# (`import_service.py`, por convocatoria) para que un id de solicitud y uno de
# convocatoria del mismo número no se bloqueen entre sí. Orden global: solicitud
# y luego folios (`approve` y `verify` toman este antes de `import_rows`); nadie
# toma el de folios primero, así que no hay ciclo.
_REQUEST_LOCK_NS = 0x7456  # "tV"

# Lo que ve el oficial en `X-Tt-Error` o en la `review_note` de una solicitud
# devuelta a revisión. Nunca el NIP.
_MSG_GONE = "La solicitud ya no existe."
_MSG_ALREADY_APPROVED = "Esa solicitud ya fue aprobada; usa Reenviar liga."
_MSG_RESOLVED = "Esa solicitud ya se resolvió."
_MSG_NO_COHORT = "La convocatoria ya no existe."
_MSG_COHORT_CLOSED = "Esa convocatoria está cerrada."
_MSG_BAD_DATA = "El número de control o el nombre no tienen formato válido."
_MSG_BAD_NIP = "El NIP debe ser exactamente 4 dígitos."
_MSG_OTHER_COHORT = "Esa persona ya tiene un proceso en otra convocatoria."
_MSG_NO_PASSWORD = ("Esa cuenta no tiene contraseña; dala de alta desde la convocatoria "
                    "y rechaza esta solicitud.")
_MSG_NO_PROCESS = "No se pudo crear el proceso; revisa los datos de la solicitud."
_MSG_ONLY_APPROVED = "Solo se reenvía la liga de solicitudes aprobadas."
_MSG_IN_ACCESS = "Ya está en Centro de Cómputo para su acceso."
_MSG_NOT_AWAITING = "Esa solicitud ya no está esperando acceso."
_MSG_RETURN_NOTE = "Escribe el motivo de la devolución."
_NOTE_LINK_COHORT_CLOSED = "La convocatoria estaba cerrada cuando se abrió la liga de activación."
_NOTE_LINK_NO_ACCOUNT = "La cuenta de ese número de control ya no existe."
_NOTE_LINK_NO_PROCESS = ("No se pudo crear el proceso al abrir la liga; revisa los datos "
                         "de la solicitud.")


def _sha256(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def _redis():
    try:
        from itcj2.core.utils.redis_conn import get_redis
        return get_redis()
    except Exception:
        return None


def _token_cache_put(raw: str) -> None:
    r = _redis()
    if r is None:
        return
    try:
        r.setex(_TOKEN_CACHE_PREFIX + _sha256(raw),
                EnrollmentRequestService._link_ttl_hours() * 3600, raw)
    except Exception as exc:
        logger.warning("No se pudo cachear el token de inscripción: %s", exc)


def _token_cache_get(digest: str) -> str | None:
    r = _redis()
    if r is None or not digest:
        return None
    try:
        val = r.get(_TOKEN_CACHE_PREFIX + digest)
    except Exception:
        return None
    if val is None:
        return None
    return val.decode("utf-8") if isinstance(val, bytes) else str(val)


def _token_cache_delete(digest: str | None) -> None:
    """Borra el claro de una liga que murió (rechazo, rotación). Best-effort:
    aunque la copia sobreviva, la BD ya no tiene el hash y nada la resuelve."""
    r = _redis()
    if r is None or not digest:
        return
    try:
        r.delete(_TOKEN_CACHE_PREFIX + digest)
    except Exception as exc:
        logger.warning("No se pudo borrar el token de inscripción de Redis: %s", exc)


def _verify_link(raw: str) -> str:
    return f"{PUBLIC_BASE_URL}/titulatec/inscripcion/verificar?t={raw}"


def _hash_ip(ip: str | None) -> str | None:
    """`sha256(ip + SECRET_KEY)`. La IP en claro nunca se guarda (§8.2)."""
    if not ip:
        return None
    from itcj2.config import get_settings
    return hashlib.sha256((ip + get_settings().SECRET_KEY).encode("utf-8")).hexdigest()


def _full_name(req) -> str:
    return " ".join(x for x in (req.last_name, req.middle_name, req.first_name) if x).strip()


def _has_process_in_other_cohort(db: Session, user_id: int, cohort_id: int) -> bool:
    """D5 exceptuando la convocatoria de la solicitud: impide entrar a una SEGUNDA
    convocatoria, no atender la propia."""
    from itcj2.apps.titulatec.models import TitulationProcess

    return (db.query(TitulationProcess)
            .filter(TitulationProcess.student_id == user_id,
                    TitulationProcess.cohort_id != cohort_id,
                    TitulationProcess.status.in_(("active", "on_hold")))
            .first()) is not None


class EnrollmentRequestService:
    """Alta, revisión, activación, rechazo y reenvío de solicitudes de inscripción."""

    @staticmethod
    def create(db: Session, cohort, data: dict, *, client_ip: str | None):
        """Alta de solicitud. Devuelve `(req|None, outcome)`.

        `outcome ∈ 'created' | 'existing_request' | 'existing_process'`. Las tres
        ramas producen la MISMA respuesta HTTP (E8), así que la ruta ignora a
        propósito el valor de retorno.

        Ninguna rama emite una liga ni escribe sobre una solicitud ajena: todas se
        disparan con un número de control que cualquiera puede teclear. La única
        que manda correo es la del proceso vivo, y lo manda al buzón
        institucional de la cuenta, cuya posesión no depende del formulario.
        """
        from itcj2.core.models.user import User
        from itcj2.apps.titulatec.models import EnrollmentRequest, TitulationProcess
        from itcj2.apps.titulatec.models.enrollment_request import OPEN_STATUSES
        from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

        control = (data.get("control_number") or "").strip()
        user = db.query(User).filter_by(control_number=control).first()

        # (a) Proceso vivo en CUALQUIER convocatoria (D5): sin fila; se le avisa
        #     a su institucional en cuál está. No hay escritura que commitear.
        if user is not None:
            proc = (db.query(TitulationProcess)
                    .filter(TitulationProcess.student_id == user.id,
                            TitulationProcess.status.in_(("active", "on_hold")))
                    .order_by(TitulationProcess.created_at.desc(),
                              TitulationProcess.id.desc())
                    .first())
            if proc is not None:
                TitulaTecEmailHelper.send_already_enrolled(db, user, proc)
                return None, "existing_process"

        # (b) Solicitud viva en esta convocatoria: no se toca. Ni correo, ni
        #     reenvío, ni los datos nuevos que traiga este intento.
        live = (db.query(EnrollmentRequest)
                .filter(EnrollmentRequest.cohort_id == cohort.id,
                        EnrollmentRequest.control_number == control,
                        EnrollmentRequest.status.in_(OPEN_STATUSES))
                .order_by(EnrollmentRequest.id.desc())
                .first())
        if live is not None:
            return live, "existing_request"

        # (c) Nueva: a la bandeja. Dos altas simultáneas del mismo control chocan
        #     en `uq_titulatec_enrollment_req_open` y la ruta cae a la misma tarjeta.
        req = EnrollmentRequest(
            cohort_id=cohort.id,
            control_number=control,
            first_name=data.get("first_name") or "",
            last_name=data.get("last_name") or "",
            middle_name=data.get("middle_name") or None,
            program_id=data.get("program_id"),
            program_text=data.get("program_text") or None,
            phone=data.get("phone") or "",
            contact_email=data.get("contact_email") or "",
            has_efirma=bool(data.get("has_efirma")),
            kind="known" if user is not None else "unknown",
            status="pending_review",
            verify_send_count=0,
            created_ip_hash=_hash_ip(client_ip),
        )
        db.add(req)
        db.commit()
        return req, "created"

    @staticmethod
    def reviewer_mode() -> str:
        """`"school_services"` (oficial) o `"computer_center"` (alterno).

        Sale de TITULATEC_ENROLLMENT_REVIEWER (+ reinicio; un valor inválido
        truena al arrancar). Los tests parchean ESTE método, nunca `get_settings`.
        """
        from itcj2.config import get_settings

        return get_settings().TITULATEC_ENROLLMENT_REVIEWER

    @staticmethod
    def reviewer_label() -> str:
        """Nombre de quien revisa según el modo: «Servicios Escolares» | «Centro de Cómputo»."""
        return _REVIEWER_LABELS[EnrollmentRequestService.reviewer_mode()]

    @staticmethod
    def approve(db: Session, req_id: int, *, nip: str, program_id: int | None,
                actor_id: int):
        """Aprueba una solicitud de la bandeja. Devuelve `(ok, detalle)`.

        En éxito `detalle` es el folio (cuenta nueva) o `""` (liga emitida o
        pasó a Centro de Cómputo); en fallo, el motivo que ve el oficial.
        Aprobable desde `pending_review` y el legado `unverified`/`verified`;
        sobre `awaiting_access` devuelve `_MSG_IN_ACCESS`.

        - CON cuenta en `core_users` (ambos modos): el NIP se ignora -> liga de
          activación (`_link_ttl_hours()`) al correo personal -> `approved`
          (`_issue_link_for_account`). La cuenta no se toca, ni siquiera se
          reactiva: eso lo hace abrir la liga (invariante 1 del módulo). Sin
          `password_hash` no hay liga (invariante 2).
        - SIN cuenta, modo OFICIAL: NO valida el NIP, NO crea usuario, NO manda
          correo -> `awaiting_access`. El NIP lo da Centro de Cómputo
          (`grant_access`).
        - SIN cuenta, modo ALTERNO: NIP obligatorio -> `_create_account` ->
          `converted`; usuario + NIP al correo personal. El caché de authz de
          los roles nuevos se tira DESPUÉS del commit.

        La convocatoria solo tiene que estar `open`: pasada `closes_at` se sigue
        aprobando lo que entró a tiempo (VENTANA, en el módulo).

        INVARIANTE: `(False, motivo)` no deja NADA escrito, ni siquiera en la
        sesión. Toda validación ocurre antes de escribir, y la única que llega
        después (no se creó el proceso) deshace su savepoint.
        """
        from itcj2.core.models.user import User
        from itcj2.apps.titulatec.models import Cohort, EnrollmentRequest
        from itcj2.apps.titulatec.services.cohort_service import CohortService
        from itcj2.apps.titulatec.services.import_service import ImportService

        req = db.get(EnrollmentRequest, req_id)
        if req is None:
            return False, _MSG_GONE
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)

        if req.status == "approved":
            return False, _MSG_ALREADY_APPROVED
        if req.status == "awaiting_access":
            return False, _MSG_IN_ACCESS
        if req.status not in _REVIEWABLE:
            return False, _MSG_RESOLVED

        cohort = db.get(Cohort, req.cohort_id)
        if cohort is None:
            return False, _MSG_NO_COHORT
        if not CohortService.accepts_enrollment_followup(cohort):
            return False, _MSG_COHORT_CLOSED

        control = (req.control_number or "").strip()
        if not CONTROL_NUMBER_RE.fullmatch(control) or not _full_name(req):
            return False, _MSG_BAD_DATA

        resolved_program_id = program_id if program_id else req.program_id
        user = db.query(User).filter_by(control_number=control).first()
        now = datetime.now()

        if user is not None:
            # ── CON cuenta: liga de activación; la cuenta no se toca ──
            ok, detalle, raw = EnrollmentRequestService._issue_link_for_account(db, req, user)
            if not ok:
                return False, detalle
            req.program_id = resolved_program_id
            req.reviewed_by_id = actor_id
            req.reviewed_at = now
            db.commit()
            _token_cache_put(raw)
            EnrollmentRequestService._mail_activation(db, req, raw)
            return True, ""

        if EnrollmentRequestService.reviewer_mode() != "computer_center":
            # ── SIN cuenta, modo oficial: a Centro de Cómputo, sin correo ──
            req.status = "awaiting_access"
            req.program_id = resolved_program_id
            req.reviewed_by_id = actor_id
            req.reviewed_at = now
            db.commit()
            return True, ""

        # ── SIN cuenta, modo alterno: usuario nuevo con el NIP, en un paso ──
        ok, detalle, summary, user = EnrollmentRequestService._create_account(
            db, req, cohort, nip=nip, program_id=resolved_program_id,
            actor_id=actor_id, approved_by_id=actor_id)
        if not ok:
            return False, detalle
        req.reviewed_by_id = actor_id
        req.reviewed_at = now
        db.commit()
        # Después del commit: antes, una lectura concurrente repoblaría el caché
        # de authz con los roles de antes de aprobar.
        ImportService.invalidate_authz((summary or {}).get("authz_touched"))
        EnrollmentRequestService._mail_access(db, req, user, nip)
        return True, detalle

    @staticmethod
    def grant_access(db: Session, req_id: int, *, nip: str, actor_id: int):
        """Centro de Cómputo da el acceso a una solicitud `awaiting_access`.

        Devuelve `(ok, detalle)`: en éxito el folio (cuenta creada) o `""` (liga
        emitida, D10); en fallo, el motivo que ve CC.

        Lock + refresh ANTES de leer el estado. Revalida todo lo que pudo
        cambiar desde que SE aprobó: que la convocatoria siga `open` (las fechas
        no cuentan, VENTANA), el formato de los datos y —D10— "¿tiene cuenta?"
        otra vez contra `core_users`:

        - SIN cuenta: NIP de 4 dígitos -> `_create_account` -> `converted`;
          commit, caché de authz, usuario + NIP al correo personal y sello de
          `access_sent_at` si salió (`_mail_access`).
        - CON cuenta (un CSV o un alta manual la creó entretanto): el NIP se
          ignora -> la misma rama que `approve()` con cuenta
          (`_issue_link_for_account`: D5 y contraseña) -> `approved`, liga al
          correo personal. Sella `access_granted_*` (CC actuó y la fila vive en
          su pestaña «Con acceso») pero NO `access_sent_at`: el envío de la liga
          lo registra `verify_sent_at`.

        `reviewed_by_id`/`reviewed_at` siguen siendo de SE: dar acceso no
        reescribe quién aprobó.

        INVARIANTE heredado de `approve()`: `(False, motivo)` no deja nada
        escrito, y el NIP nunca sale (log, `detalle`, payload).
        """
        from itcj2.core.models.user import User
        from itcj2.apps.titulatec.models import Cohort, EnrollmentRequest
        from itcj2.apps.titulatec.services.cohort_service import CohortService
        from itcj2.apps.titulatec.services.import_service import ImportService

        req = db.get(EnrollmentRequest, req_id)
        if req is None:
            return False, _MSG_GONE
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)

        if req.status != "awaiting_access":
            return False, _MSG_NOT_AWAITING

        cohort = db.get(Cohort, req.cohort_id)
        if cohort is None:
            return False, _MSG_NO_COHORT
        if not CohortService.accepts_enrollment_followup(cohort):
            return False, _MSG_COHORT_CLOSED

        control = (req.control_number or "").strip()
        if not CONTROL_NUMBER_RE.fullmatch(control) or not _full_name(req):
            return False, _MSG_BAD_DATA

        user = db.query(User).filter_by(control_number=control).first()
        if user is not None:
            # ── D10: apareció una cuenta; liga, el NIP se ignora ──
            ok, detalle, raw = EnrollmentRequestService._issue_link_for_account(db, req, user)
            if not ok:
                return False, detalle
            req.access_granted_by_id = actor_id
            req.access_granted_at = datetime.now()
            db.commit()
            _token_cache_put(raw)
            EnrollmentRequestService._mail_activation(db, req, raw)
            return True, ""

        ok, detalle, summary, user = EnrollmentRequestService._create_account(
            db, req, cohort, nip=nip, program_id=req.program_id,
            actor_id=actor_id, approved_by_id=req.reviewed_by_id)
        if not ok:
            return False, detalle
        db.commit()
        ImportService.invalidate_authz((summary or {}).get("authz_touched"))
        EnrollmentRequestService._mail_access(db, req, user, nip)
        return True, detalle

    @staticmethod
    def return_to_review(db: Session, req_id: int, *, note: str, actor_id: int):
        """Centro de Cómputo devuelve a SE una solicitud `awaiting_access`.

        Devuelve `(ok, detalle)`. Nota obligatoria (se recorta a 2000, como el
        motivo de `reject`); la solicitud vuelve a `pending_review` con
        `returned_by_id`/`returned_at`/`return_note`. `reviewed_*` y
        `review_note` no se tocan (son de SE). SIN correo: el alumno no se
        entera del paso intermedio.
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest

        motivo = (note or "").strip()
        if not motivo:
            return False, _MSG_RETURN_NOTE
        req = db.get(EnrollmentRequest, req_id)
        if req is None:
            return False, _MSG_GONE
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)

        if req.status != "awaiting_access":
            return False, _MSG_NOT_AWAITING

        req.status = "pending_review"
        req.returned_by_id = actor_id
        req.returned_at = datetime.now()
        req.return_note = motivo[:2000]
        db.commit()
        return True, ""

    @staticmethod
    def _issue_link_for_account(db: Session, req, user):
        """Rama CON cuenta de `approve()` y de `grant_access()` (D10).

        Devuelve `(ok, detalle, raw)`. Valida D5 (la cuenta ya tiene proceso en
        OTRA convocatoria) y la contraseña (invariante 2) ANTES de escribir; en
        éxito emite la liga (`_issue_activation`), fija el contador y deja la
        solicitud `approved`. No toca la cuenta, no commitea ni manda: el
        llamador sella sus columnas, commitea, cachea el claro y manda
        (`_mail_activation`), en ese orden.
        """
        if _has_process_in_other_cohort(db, user.id, req.cohort_id):
            return False, _MSG_OTHER_COHORT, None
        if not user.password_hash:
            return False, _MSG_NO_PASSWORD, None
        raw = EnrollmentRequestService._issue_activation(req)
        req.verify_send_count = 1
        req.status = "approved"
        return True, "", raw

    @staticmethod
    def _create_account(db: Session, req, cohort, *, nip: str, program_id: int | None,
                        actor_id: int, approved_by_id: int | None):
        """Crea la cuenta NUEVA de una solicitud sin cuenta. `(ok, detalle, summary, user)`.

        Lo usan `approve()` (modo alterno) y `grant_access()`. NIP de 4 dígitos
        -> `User` con `hash_nip(nip)` (nunca `set_initial_credential`, que
        pondría el número de control, dato público), `must_change_password` y el
        alias legado `graduate` -> proceso y roles de egresado (`import_rows`
        con `commit=False` y `repair_credentials=False`) -> perfil -> solicitud
        `converted` con `access_granted_*` -> `ProcessEvent` con
        `approved_by_id` (quien aprobó) y `granted_by_id` (quien dio el acceso),
        SIN el NIP.

        Todo corre en un SAVEPOINT: si no se crea el proceso se deshace y
        devuelve `(False, _MSG_NO_PROCESS, None, None)` sin dejar nada escrito;
        una excepción lo deshace y sube. No commitea, no tira el caché de authz
        ni manda correo: eso es del llamador, después de SU commit, con
        `summary["authz_touched"]` y `_mail_access`.
        """
        from itcj2.core.models.role import Role
        from itcj2.core.models.user import User
        from itcj2.core.services.student_profile_service import StudentProfileService
        from itcj2.core.utils.security import hash_nip
        from itcj2.apps.titulatec.models import ProcessEvent, TitulationProcess
        from itcj2.apps.titulatec.services.import_service import (
            GRADUATE_ROLE, ImportService,
        )

        if not re.fullmatch(r"\d{4}", nip or ""):
            return False, _MSG_BAD_NIP, None, None
        control = (req.control_number or "").strip()

        savepoint = db.begin_nested()
        try:
            # El alias legado nace `graduate`: el mismo que `import_rows` le deja
            # a una cuenta que ya existía (`_sync_graduate_roles`).
            graduate_role = db.query(Role).filter_by(name=GRADUATE_ROLE).first()
            user = User(
                username=control, control_number=control,
                first_name=req.first_name, last_name=req.last_name,
                middle_name=req.middle_name or None,
                email=None,
                role_id=graduate_role.id if graduate_role else None,
                is_active=True, must_change_password=True,
            )
            user.password_hash = hash_nip(nip)   # nunca `set_initial_credential`
            db.add(user)
            db.flush()

            # `commit=False`: `import_rows` solo hace `flush` y el llamador es
            # dueño único de su transacción (Finding 2, ronda 1 de revisión).
            # Por lo mismo, el caché de authz de los roles que deja lo tira el
            # llamador después de su commit, con los pares del summary.
            summary = ImportService.import_rows(
                db, cohort,
                [{"control_number": control, "full_name": _full_name(req), "email": None,
                  "program_id": program_id, "modality_id": None}],
                actor_id=actor_id, source="enrollment_request",
                repair_credentials=False, commit=False,
            )
            proc = (db.query(TitulationProcess)
                    .filter_by(student_id=user.id, cohort_id=req.cohort_id).first())
            if proc is None:
                savepoint.rollback()
                return False, _MSG_NO_PROCESS, None, None

            # El perfil de un usuario recién creado sí se llena: es lo único que
            # se sabe de él y no pisa nada de nadie.
            StudentProfileService.set_fields(
                db, user.id,
                contact_email=req.contact_email, phone=req.phone,
                has_efirma=req.has_efirma, program_text=req.program_text,
                program_id=program_id,
            )
            now = datetime.now()
            req.status = "converted"
            req.program_id = program_id
            req.converted_process_id = proc.id
            req.access_granted_by_id = actor_id
            req.access_granted_at = now
            db.add(ProcessEvent(
                process_id=proc.id, actor_id=actor_id,
                event_type="enrollment_self_service", phase_number=0,
                # Se muestra en el expediente: aquí NO va el NIP.
                payload={"request_id": req.id, "folio": proc.folio,
                         "preexisting_process": False, "reviewed": True,
                         "activation": "nip_personal_email",
                         "approved_by_id": approved_by_id,
                         "granted_by_id": actor_id},
            ))
            folio = proc.folio
            savepoint.commit()
        except Exception:
            if savepoint.is_active:
                savepoint.rollback()
            raise
        return True, folio, summary, user

    @staticmethod
    def _mail_access(db: Session, req, user, nip: str) -> bool:
        """Manda usuario + NIP al correo personal. Llamar SOLO después del commit.

        Si el correo sale, sella `access_sent_at` en un commit propio (mismo
        patrón que `_mail_activation`/`verify_sent_at`); si no, la fila queda
        con `access_granted_at` y sin `access_sent_at`: «correo no enviado».
        Un fallo al sellar no deshace nada: el correo ya salió.
        """
        from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

        rid = req.id
        ok = TitulaTecEmailHelper.send_enrollment_approved(db, req, user, nip=nip)
        if ok:
            try:
                req.access_sent_at = datetime.now()
                db.commit()
            except Exception:
                logger.warning("No se pudo sellar el envío del acceso de la solicitud %s", rid)
                try:
                    db.rollback()
                except Exception:      # pragma: no cover - sesión ya inservible
                    pass
        return ok

    @staticmethod
    def verify(db: Session, token: str):
        """Abre la liga de activación. Devuelve `(req|None, outcome)`.

        `outcome ∈ 'converted' | 'already_converted' | 'pending_review' |
        'expired' | 'invalid'`. Solo una solicitud `approved` con la liga vigente
        se convierte; `pending_review`, `rejected`, el legado y un token
        desconocido son `invalid` (invariante: nadie obtiene acceso sin la liga
        de una solicitud aprobada).

        IDEMPOTENTE: Outlook Safe Links y los escáneres corporativos pre-abren
        la liga en cuanto llega. Una convertida devuelve `already_converted` con
        la misma tarjeta, y el hash no se borra al convertir para eso.

        La comparación decisiva usa `hmac.compare_digest`: es una credencial al
        portador y un `==` de Python filtraría por temporización cuántos bytes
        acertó quien lo intenta. Se repite DESPUÉS del lock porque, mientras se
        esperaba, la bandeja pudo rotar la liga (reenvío) o matarla (rechazo).

        Lock por solicitud + `db.refresh(req)` antes de leer el estado: el
        prefetch del escáner en paralelo con el clic humano es el caso NORMAL.

        La primera apertura sella `verified_at`, también cuando la liga ya venció
        (la bandeja muestra "abierta" y el oficial sabe que la persona lo intentó).

        Si `_convert` falla una revalidación, la solicitud vuelve a
        `pending_review` con la nota y la liga muere. `_convert` corre en un
        SAVEPOINT: al deshacerlo desaparece lo que `import_rows` ya había hecho
        `flush` (rol de la app, proceso) sin soltar el lock ni perder lo que esta
        pasada decidió. Esa era la trampa de la revisión final §3: un `rollback()`
        completo tira también `verified_at` y expira la solicitud. Una excepción
        no es una revalidación: sube a la ruta, que hace `rollback()` y la
        solicitud sigue aprobada con la liga viva.

        El aviso con folio (`send_enrollment_done`, al institucional) sale
        después del commit.
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest, TitulationProcess
        from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

        if not token:
            return None, "invalid"
        digest = _sha256(token)
        # La búsqueda por índice la hace O(1); la comparación constante decide.
        req = (db.query(EnrollmentRequest)
               .filter(EnrollmentRequest.verify_token_hash == digest).first())
        if req is None or not hmac.compare_digest(req.verify_token_hash or "", digest):
            return None, "invalid"

        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)
        if not hmac.compare_digest(req.verify_token_hash or "", digest):
            return None, "invalid"

        if req.status == "converted":
            return req, "already_converted"
        if req.status != "approved":
            return req, "invalid"

        if req.verified_at is None:
            req.verified_at = datetime.now()
        if req.verify_expires_at is None or req.verify_expires_at < datetime.now():
            db.commit()
            return req, "expired"

        touched: list = []
        savepoint = db.begin_nested()
        try:
            ok, detail = EnrollmentRequestService._convert(db, req, authz_touched=touched)
        except Exception:
            if savepoint.is_active:
                savepoint.rollback()
            raise

        if not ok:
            savepoint.rollback()
            # Se reaplica todo lo que esta pasada decide; el lock sigue tomado
            # porque es de la transacción externa, no del savepoint.
            muerta = req.verify_token_hash
            req.status = "pending_review"
            req.review_note = detail
            req.verified_at = req.verified_at or datetime.now()
            req.verify_token_hash = None
            req.verify_expires_at = None
            db.commit()
            _token_cache_delete(muerta)
            return req, "pending_review"

        savepoint.commit()
        db.commit()
        # Después del commit, con los pares que dejó `import_rows` dentro de
        # `_convert` (ver `ImportService.invalidate_authz`).
        from itcj2.apps.titulatec.services.import_service import ImportService
        ImportService.invalidate_authz(touched)
        proc = db.get(TitulationProcess, req.converted_process_id)
        if proc is not None:
            TitulaTecEmailHelper.send_enrollment_done(db, req, proc)
        return req, "converted"

    @staticmethod
    def _convert(db: Session, req, *, authz_touched: list | None = None):
        """Inscribe la CUENTA EXISTENTE de una solicitud aprobada. `(ok, detalle)`.

        En éxito `detalle` es el folio; en fallo, la `review_note` para la bandeja.
        Todo lo que pudo cambiar desde la aprobación se revisa ANTES de
        `import_rows`: que la convocatoria siga `open` (las fechas no cuentan,
        ver VENTANA en el módulo), formato de los datos, que la
        cuenta siga existiendo, D5 y la contraseña.

        Solo escribe proceso y roles de egresado (vía `import_rows` con
        `commit=False` y `repair_credentials=False`, que no toca credencial,
        `is_active` ni `must_change_password` de una cuenta que ya existe: le deja
        `graduate` y le quita `student`), la solicitud y el `ProcessEvent`. NADA
        del perfil (invariante 1 del módulo). Su ÚNICA escritura propia sobre la
        cuenta es reactivarla si estaba desactivada, con `reactivated` en el
        payload: la excepción aprobada del invariante 1. No commitea, no tira el
        caché de authz ni manda correo: eso es de `verify()`, que recibe en
        `authz_touched` los pares que `import_rows` cambió.

        No se ramifica sobre `processes_created`: si un CSV creó el proceso
        mientras la persona no abría la liga, la conversión es igual de exitosa.
        Solo la AUSENCIA de proceso es un fallo.
        """
        from itcj2.core.models.user import User
        from itcj2.apps.titulatec.models import Cohort, ProcessEvent, TitulationProcess
        from itcj2.apps.titulatec.services.cohort_service import CohortService
        from itcj2.apps.titulatec.services.import_service import ImportService

        # El estado se revisa sobre la convocatoria GUARDADA en la solicitud: el
        # periodo va dentro del folio y de la ruta en disco.
        cohort = db.get(Cohort, req.cohort_id)
        if not CohortService.accepts_enrollment_followup(cohort):
            return False, _NOTE_LINK_COHORT_CLOSED

        control = (req.control_number or "").strip()
        full_name = _full_name(req)
        if not CONTROL_NUMBER_RE.fullmatch(control) or not full_name:
            return False, _MSG_BAD_DATA

        user = db.query(User).filter_by(control_number=control).first()
        if user is None:
            return False, _NOTE_LINK_NO_ACCOUNT
        if _has_process_in_other_cohort(db, user.id, req.cohort_id):
            return False, _MSG_OTHER_COHORT
        if not user.password_hash:
            return False, _MSG_NO_PASSWORD

        ya_existia = (db.query(TitulationProcess)
                      .filter_by(student_id=user.id, cohort_id=req.cohort_id)
                      .first()) is not None

        summary = ImportService.import_rows(
            db, cohort,
            [{"control_number": control, "full_name": full_name, "email": None,
              "program_id": req.program_id, "modality_id": None}],
            actor_id=None, source="self_service", repair_credentials=False,
            commit=False,
        )
        if authz_touched is not None:
            authz_touched.extend((summary or {}).get("authz_touched") or ())

        proc = (db.query(TitulationProcess)
                .filter_by(student_id=user.id, cohort_id=req.cohort_id).first())
        if proc is None:
            return False, _NOTE_LINK_NO_PROCESS

        # EXCEPCIÓN APROBADA al invariante 1 (2026-09-15): la liga de una
        # solicitud aprobada reactiva la cuenta desactivada. Es la única
        # escritura sobre la cuenta además de roles y proceso, y va aquí, con el
        # proceso ya creado: una revalidación fallida no llega, y cualquier
        # fallo posterior la deshace con el savepoint de `verify`.
        reactivada = not user.is_active
        if reactivada:
            user.is_active = True

        req.status = "converted"
        req.converted_process_id = proc.id
        db.add(ProcessEvent(
            process_id=proc.id, actor_id=None,
            event_type="enrollment_self_service", phase_number=0,
            payload={"request_id": req.id, "folio": proc.folio,
                     "preexisting_process": ya_existia,
                     "activation": "personal_email_link",
                     "approved_by_id": req.reviewed_by_id,
                     # Rastro de la excepción: la bandeja la anuncia antes de
                     # aprobar y el expediente la conserva después.
                     "reactivated": reactivada},
        ))
        return True, proc.folio

    @staticmethod
    def reject(db: Session, req_id: int, *, note: str, actor_id: int) -> bool:
        """Rechaza con motivo obligatorio. `True` si se rechazó.

        Aplica desde `pending_review`, `awaiting_access` (SE cancela una que
        esperaba a Centro de Cómputo), `approved` (cancela una liga en camino) y
        el legado. La liga muere en BD y en Redis; el motivo se manda al correo
        personal después del commit, firmado por `reviewer_label()`. El índice
        parcial deja volver a intentar.

        Si el correo SALE, sella `rejection_sent_at` en un commit propio, mismo
        patrón que `_mail_activation`/`verify_sent_at`: un fallo al sellar no
        deshace nada (el correo ya salió). `NULL` es lo que la bandeja pinta
        como "correo no enviado" en una fila `rejected`.
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest
        from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

        motivo = (note or "").strip()
        if not motivo:
            return False
        req = db.get(EnrollmentRequest, req_id)
        if req is None:
            return False
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)
        if req.status not in _REJECTABLE:
            return False

        muerta = req.verify_token_hash
        req.status = "rejected"
        req.review_note = motivo[:2000]
        req.reviewed_by_id = actor_id
        req.reviewed_at = datetime.now()
        req.verify_token_hash = None
        req.verify_expires_at = None
        db.commit()
        _token_cache_delete(muerta)
        if TitulaTecEmailHelper.send_enrollment_rejected(db, req):
            try:
                req.rejection_sent_at = datetime.now()
                db.commit()
            except Exception:
                logger.warning(
                    "No se pudo sellar el envío del rechazo de la solicitud %s", req_id)
                try:
                    db.rollback()
                except Exception:      # pragma: no cover - sesión ya inservible
                    pass
        return True

    @staticmethod
    def resend_link(db: Session, req_id: int):
        """Reenvío desde la bandeja. Devuelve `(ok, detalle)`.

        Solo para `approved`, y ROTA la liga: hash y vencimiento nuevos, la copia
        vieja se borra de Redis y la liga anterior deja de servir. Rotar es seguro
        aquí porque el actor está autenticado y la ruta ya lo acotó por carrera;
        el veto a rotar es del reenvío PÚBLICO. No lleva presupuesto.

        Con la convocatoria `closed` (pausa) no se emite liga nueva; pasada
        `closes_at` sí (VENTANA, en el módulo).
        """
        from itcj2.apps.titulatec.models import Cohort, EnrollmentRequest
        from itcj2.apps.titulatec.services.cohort_service import CohortService

        req = db.get(EnrollmentRequest, req_id)
        if req is None:
            return False, _MSG_GONE
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)
        if req.status != "approved":
            return False, _MSG_ONLY_APPROVED
        cohort = db.get(Cohort, req.cohort_id)
        if cohort is None:
            return False, _MSG_NO_COHORT
        if not CohortService.accepts_enrollment_followup(cohort):
            return False, _MSG_COHORT_CLOSED

        muerta = req.verify_token_hash
        raw = EnrollmentRequestService._issue_activation(req)
        req.verify_send_count = (req.verify_send_count or 0) + 1
        db.commit()
        _token_cache_delete(muerta)
        _token_cache_put(raw)
        EnrollmentRequestService._mail_activation(db, req, raw)
        return True, ""

    @staticmethod
    def resend(db: Session, control_number: str, contact_email: str) -> str:
        """Reenvío PÚBLICO de la liga. Devuelve `'sent'` o `'noop'`.

        Solo actúa sobre una solicitud `approved` que case con
        (control_number, contact_email), y reenvía EL MISMO token (el claro de
        Redis): no rota ni alarga la vida de la liga, que las fija la bandeja.
        Presupuesto: `MAX_VERIFY_SENDS` envíos en total y al menos
        `MIN_SECONDS_BETWEEN_SENDS` entre uno y otro.

        `'noop'` cubre TODO lo que no manda correo: no casa, otro estado, tope,
        muy pronto, convocatoria no `open` (las fechas no cuentan: VENTANA, en el
        módulo), liga vencida y la falta del claro en Redis
        (se falla cerrado). La respuesta HTTP es la misma en todos los casos: esa
        igualdad es un invariante (§6.8), no un descuido; darle tarjeta propia a
        cualquiera de ellos haría del endpoint un oráculo de existencia.

        La llave nunca es el `id`: es un BigInteger secuencial y cualquiera
        enumeraría 1..N para disparar correos a buzones ajenos.
        """
        from sqlalchemy import func
        from itcj2.core.utils.email_tools import normalize_email
        from itcj2.apps.titulatec.models import Cohort, EnrollmentRequest
        from itcj2.apps.titulatec.services.cohort_service import CohortService

        control = (control_number or "").strip()
        email = normalize_email(contact_email) or ""
        if not control or not email:
            return "noop"

        req = (db.query(EnrollmentRequest)
               .filter(EnrollmentRequest.control_number == control,
                       func.lower(EnrollmentRequest.contact_email) == email.lower(),
                       EnrollmentRequest.status == "approved")
               .order_by(EnrollmentRequest.id.desc())
               .first())
        if req is None:
            return "noop"
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)
        if req.status != "approved":
            return "noop"

        cohort = db.get(Cohort, req.cohort_id)
        if not CohortService.accepts_enrollment_followup(cohort):
            return "noop"
        now = datetime.now()
        if (req.verify_send_count or 0) >= MAX_VERIFY_SENDS:
            return "noop"
        if (req.verify_sent_at is not None
                and (now - req.verify_sent_at).total_seconds() < MIN_SECONDS_BETWEEN_SENDS):
            return "noop"
        if req.verify_expires_at is None or req.verify_expires_at < now:
            return "noop"
        raw = _token_cache_get(req.verify_token_hash or "")
        if raw is None:
            return "noop"

        req.verify_send_count = (req.verify_send_count or 0) + 1
        db.commit()
        return "sent" if EnrollmentRequestService._mail_activation(db, req, raw) else "noop"

    @staticmethod
    def _link_ttl_hours() -> int:
        """Vida de la liga de activación, en horas (TITULATEC_ENROLLMENT_LINK_TTL_DAYS).

        ÚNICA fuente: el vencimiento en BD (`_issue_activation`), el TTL del
        claro en Redis (`_token_cache_put`) y los "N días" del correo
        (`TitulaTecEmailHelper.send_verify_enrollment`) la llaman en cada uso,
        así que no pueden divergir. Los tests parchean ESTE método, nunca
        `get_settings`.
        """
        from itcj2.config import get_settings

        return get_settings().TITULATEC_ENROLLMENT_LINK_TTL_DAYS * 24

    @staticmethod
    def _issue_activation(req) -> str:
        """Emite (o rota) la liga de activación de `req`. Devuelve el claro.

        Solo sella la fila; el llamador fija el contador, commitea, cachea el
        claro y manda (`_mail_activation`), en ese orden. `verify_sent_at` y
        `verified_at` vuelven a NULL: "enviada" y "abierta" hablan de la liga
        vigente, no de una anterior.
        """
        raw = secrets.token_urlsafe(32)
        req.verify_token_hash = _sha256(raw)
        req.verify_expires_at = (datetime.now()
                                 + timedelta(hours=EnrollmentRequestService._link_ttl_hours()))
        req.verify_sent_to = req.contact_email
        req.verify_sent_at = None
        req.verified_at = None
        return raw

    @staticmethod
    def _mail_activation(db: Session, req, raw: str) -> bool:
        """Manda la liga al correo personal. Llamar SOLO después del commit.

        Si el correo sale, sella `verify_sent_at` en un commit propio; si no, la
        bandeja lo muestra como "correo no enviado" y ofrece reenviar. Un fallo
        al sellar no deshace nada: el correo ya salió.
        """
        from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

        rid = req.id
        ok = TitulaTecEmailHelper.send_verify_enrollment(db, req, link=_verify_link(raw))
        if ok:
            try:
                req.verify_sent_at = datetime.now()
                db.commit()
            except Exception:
                logger.warning("No se pudo sellar el envío de la liga de la solicitud %s", rid)
                try:
                    db.rollback()
                except Exception:      # pragma: no cover - sesión ya inservible
                    pass
        return ok

    @staticmethod
    def stats(db: Session, *, scope, cohort_id: int | None = None, today: date | None = None):
        """KPIs y "por año de ingreso" de la bandeja. Puro respecto a HTTP: solo
        lee, no lanza, no depende de `Request`. `pages/requests_admin.py::_body_ctx`
        solo la invoca.

        `scope`: `'ALL'` o `set[int]` de `program_id`, el MISMO criterio que
        `scope_service.officer_programs` — el mismo con el que la bandeja filtra su
        listado (invariante: los KPIs y el listado cuentan sobre el mismo universo).
        Un set vacío devuelve todo en cero sin tocar la BD: el caller real
        (`_body_ctx`) ya corta antes con `no_programs`, esto es solo para no
        reventar si alguien la llama igual.

        Devuelve `{"counts": {...}, "by_year": [...], "year_max": int}`:

        - `counts`: conteos de SOLICITUDES (una fila = una solicitud) agrupados con
          `_STATUS_GROUP` — `total`, `review` (por revisar, incluido el legado),
          `access` (en Centro de Cómputo, `awaiting_access`), `sent` (liga
          enviada), `converted` (inscritas), `rejected`. Mismo alcance
          y `cohort_id` que el listado, pero SIN filtro de pestaña ni el límite de
          300 filas: es el universo completo de la convocatoria (o de todas).
        - `by_year`: una entrada por año de ingreso (`entry_year`, orden
          descendente, "Sin año" al final), contando PERSONAS únicas (número de
          control distinto) por la solicitud MÁS RECIENTE (`created_at`, `id`) de
          cada una dentro de este mismo alcance/convocatoria — no solicitudes:
          dos intentos de la misma persona no deben contarla dos veces. Cada
          entrada trae el mismo desglose de `counts` sobre esas personas.
        - `year_max`: el `total` más alto de `by_year` (0 si está vacío), para que
          la plantilla dibuje la barra de cada año proporcional al máximo sin
          tener que recalcularlo (p. ej. como `max` de un `<meter>`).
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest

        counts = {"total": 0, "review": 0, "access": 0, "sent": 0, "converted": 0,
                  "rejected": 0}
        if scope != "ALL" and not scope:
            return {"counts": counts, "by_year": [], "year_max": 0}

        q = db.query(EnrollmentRequest.id, EnrollmentRequest.control_number,
                     EnrollmentRequest.status, EnrollmentRequest.created_at)
        if scope != "ALL":
            q = q.filter(EnrollmentRequest.program_id.in_(scope))
        if cohort_id:
            q = q.filter(EnrollmentRequest.cohort_id == cohort_id)

        # Más reciente por control: (created_at, id) más alto gana. `created_at`
        # trae `server_default=NOW()` (nunca NULL en una fila real), `datetime.min`
        # es solo para que el `max()` no reviente si alguna vez lo fuera.
        latest_by_control: dict[str, tuple] = {}
        for rid, control, status, created_at in q.all():
            counts["total"] += 1
            counts[_STATUS_GROUP.get(status, "review")] += 1
            if not control:
                continue
            key = (created_at or datetime.min, rid)
            if control not in latest_by_control or key > latest_by_control[control][0]:
                latest_by_control[control] = (key, status)

        years: dict[str, dict] = {}
        for control, (_key, status) in latest_by_control.items():
            year = entry_year(control, today)
            if year not in years:
                # `slug` es un token seguro para `id="..."` en la plantilla: "Sin
                # año" trae espacio y una ñ, y un `id` con espacio es HTML
                # inválido (rompe el emparejado de Idiomorph). Los años reales ya
                # son 4 dígitos: sirven tal cual.
                slug = year if year != "Sin año" else "sin-anio"
                years[year] = {"year": year, "slug": slug, "total": 0, "review": 0,
                               "access": 0, "sent": 0, "converted": 0, "rejected": 0}
            bucket = years[year]
            bucket["total"] += 1
            bucket[_STATUS_GROUP.get(status, "review")] += 1

        by_year = sorted(
            years.values(),
            key=lambda y: (0, -int(y["year"])) if y["year"] != "Sin año" else (1, 0),
        )
        year_max = max((y["total"] for y in by_year), default=0)

        # Lo que se lee con el bloque CERRADO (`<summary>` de la bandeja): con
        # 20+ generaciones el bloque abierto no cabe en pantalla, así que el
        # resumen tiene que bastar para decidir si vale la pena abrirlo.
        # `peak` desempata por el año MÁS RECIENTE; «Sin año» no compite ni
        # entra al rango.
        reales = [y for y in by_year if y["year"] != "Sin año"]
        pico = max(reales, key=lambda y: (y["total"], int(y["year"])), default=None)
        summary = {
            "people": len(latest_by_control),
            "generations": len(by_year),
            "span": (f"{reales[-1]['year']}–{reales[0]['year']}"
                     if len(reales) > 1 else (reales[0]["year"] if reales else "")),
            "peak": ({"year": pico["year"], "total": pico["total"]} if pico else None),
        }
        return {"counts": counts, "by_year": by_year, "year_max": year_max,
                "summary": summary}
