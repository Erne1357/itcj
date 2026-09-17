"""Solicitudes de auto-inscripción a una convocatoria de titulación.

FLUJO (2026-09-15; manda sobre §6.6-6.10 del diseño original). Toda solicitud
pasa por la bandeja de Servicios Escolares y el acceso llega SOLO por correo:

    create()  ─► pending_review                          sin token, sin correo
    approve() ─┬─ SIN cuenta en core_users ─► converted   usuario + NIP al correo personal
               └─ CON cuenta ───────────────► approved    liga de activación al correo personal
    verify()  ─── approved y liga vigente ──► converted   proceso + rol graduate; folio al institucional
               └─ falla una revalidación ───► pending_review  (review_note = motivo)
    reject()  ─── pending_review | approved | legado ─► rejected  (la liga muere)

`unverified` y `verified` son estados LEGADO del flujo con liga previa: ya no se
escriben, pero sus filas se pueden aprobar o rechazar desde la bandeja.

"¿TIENE CUENTA?" SE DECIDE CONTRA `core_users` AL APROBAR, nunca con `kind` (que
`create()` guarda solo para mostrar): si un CSV creó la cuenta después de enviado
el formulario, la solicitud va por la rama con cuenta.

RIESGO ACEPTADO Y SU CONTENCIÓN (invariante; sustituye a los rulings R5, B1 y
D17). La liga de una cuenta existente viaja al correo que TECLEÓ el solicitante:
quien escriba un número de control ajeno con su correo y pase la revisión puede
dejar inscrita a esa persona. Para que no escale:

  1. Sobre una cuenta existente JAMÁS se escribe `password_hash`,
     `must_change_password` ni `core_student_profile` a partir de la solicitud,
     ni en `approve()` ni en `verify()`/`_convert()`. Lo único que recibe es el
     proceso y los roles de egresado (`graduate`, que desplaza a `student`; ver
     `ImportService.import_rows`).
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

Una cuenta NUEVA solo conoce su NIP por el correo que manda `approve()`.

TOKEN (E7). La BD guarda SOLO `sha256(token)` y la comparación decisiva usa
`hmac.compare_digest`. El texto claro vive en Redis bajo `tt:enroll:tok:<sha256>`
lo mismo que la liga, y solo para que el reenvío PÚBLICO no rote: rotar desde un
endpoint anónimo dejaría a un extraño matar la liga de otra persona. Sin esa
copia el reenvío público falla CERRADO. La bandeja sí rota: su actor está
autenticado y acotado por carrera.

CORREO SIEMPRE DESPUÉS DEL COMMIT. `msgraph_mail` es un `requests.post`
síncrono: dentro de la transacción retendría los advisory locks, y un correo
mandado antes de un commit que falla habla de algo que no existe. Ningún método
del helper lanza, así que un fallo de buzón no revierte nada ya commiteado.

CONCURRENCIA. Toda transición de una solicitud (`approve`, `verify`, `reject`,
`resend_link`, `resend`) toma `pg_advisory_xact_lock(_REQUEST_LOCK_NS, req.id)`
y hace `db.refresh(req)` ANTES de leer el estado: bajo READ COMMITTED, quien
esperó el lock puede seguir teniendo en memoria el estado de antes de esperarlo.
Los tests estructurales de cada método fijan ese orden.
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

STATUSES = ("unverified", "verified", "pending_review", "approved", "rejected", "converted")

# Desde dónde la bandeja aprueba (y rechaza, junto con `approved`).
_REVIEWABLE = ("pending_review", "unverified", "verified")
_REJECTABLE = _REVIEWABLE + ("approved",)

# Agrupa los 6 STATUSES en los 4 cubos que pinta la bandeja (KPIs y "por año de
# ingreso", `EnrollmentRequestService.stats`): el legado `unverified`/`verified`
# cuenta como "por revisar", igual que en `_TAB_STATUSES` de `pages/requests_admin.py`.
_STATUS_GROUP = {s: "review" for s in _REVIEWABLE}
_STATUS_GROUP.update(approved="sent", converted="converted", rejected="rejected")

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

VERIFY_TTL_HOURS = 168           # la liga de activación vive 7 días
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
_MSG_COHORT_CLOSED = "Esa convocatoria está cerrada; abre su ventana primero."
_MSG_BAD_DATA = "El número de control o el nombre no tienen formato válido."
_MSG_BAD_NIP = "El NIP debe ser exactamente 4 dígitos."
_MSG_OTHER_COHORT = "Esa persona ya tiene un proceso en otra convocatoria."
_MSG_NO_PASSWORD = ("Esa cuenta no tiene contraseña; dala de alta desde la convocatoria "
                    "y rechaza esta solicitud.")
_MSG_NO_PROCESS = "No se pudo crear el proceso; revisa los datos de la solicitud."
_MSG_ONLY_APPROVED = "Solo se reenvía la liga de solicitudes aprobadas."
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
        r.setex(_TOKEN_CACHE_PREFIX + _sha256(raw), VERIFY_TTL_HOURS * 3600, raw)
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
    def approve(db: Session, req_id: int, *, nip: str, program_id: int | None,
                actor_id: int):
        """Aprueba una solicitud de la bandeja. Devuelve `(ok, detalle)`.

        En éxito `detalle` es el folio (cuenta nueva) o `""` (liga emitida); en
        fallo, el motivo que ve el oficial. Aprobable desde `pending_review` y el
        legado `unverified`/`verified`.

        - SIN cuenta en `core_users`: NIP obligatorio -> usuario con
          `hash_nip(nip)`, `must_change_password` y el alias legado `graduate`
          -> proceso y roles de egresado (`import_rows`) -> perfil ->
          `converted`; usuario + NIP al correo personal. El caché de authz de
          esos roles se tira DESPUÉS del commit (`ImportService.invalidate_authz`).
        - CON cuenta: el NIP se ignora -> liga de activación de 7 días al correo
          personal -> `approved`. La cuenta no se toca, ni siquiera se reactiva:
          eso lo hace abrir la liga (invariante 1 del módulo). Sin
          `password_hash` no hay liga (invariante 2).

        EL NIP NUNCA SALE DE AQUÍ: no se loguea, no va en `X-Tt-Error` (`detalle`
        se emite tal cual en una cabecera) ni en el payload del `ProcessEvent`.

        INVARIANTE: `(False, motivo)` no deja NADA escrito, ni siquiera en la
        sesión. Toda validación ocurre antes de escribir, y la única que llega
        después (no se creó el proceso) deshace su savepoint.
        """
        from itcj2.core.models.role import Role
        from itcj2.core.models.user import User
        from itcj2.core.services.student_profile_service import StudentProfileService
        from itcj2.core.utils.security import hash_nip
        from itcj2.apps.titulatec.models import (
            Cohort, EnrollmentRequest, ProcessEvent, TitulationProcess,
        )
        from itcj2.apps.titulatec.services.cohort_service import CohortService
        from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper
        from itcj2.apps.titulatec.services.import_service import ImportService

        req = db.get(EnrollmentRequest, req_id)
        if req is None:
            return False, _MSG_GONE
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)

        if req.status == "approved":
            return False, _MSG_ALREADY_APPROVED
        if req.status not in _REVIEWABLE:
            return False, _MSG_RESOLVED

        cohort = db.get(Cohort, req.cohort_id)
        if cohort is None:
            return False, _MSG_NO_COHORT
        if not CohortService.is_public_enrollment_open(cohort):
            return False, _MSG_COHORT_CLOSED

        control = (req.control_number or "").strip()
        full_name = _full_name(req)
        if not CONTROL_NUMBER_RE.fullmatch(control) or not full_name:
            return False, _MSG_BAD_DATA

        resolved_program_id = program_id if program_id else req.program_id
        user = db.query(User).filter_by(control_number=control).first()
        now = datetime.now()

        if user is not None:
            # ── CON cuenta: liga de activación; la cuenta no se toca ──
            if _has_process_in_other_cohort(db, user.id, req.cohort_id):
                return False, _MSG_OTHER_COHORT
            if not user.password_hash:
                return False, _MSG_NO_PASSWORD
            raw = EnrollmentRequestService._issue_activation(req)
            req.verify_send_count = 1
            req.status = "approved"
            req.program_id = resolved_program_id
            req.reviewed_by_id = actor_id
            req.reviewed_at = now
            db.commit()
            _token_cache_put(raw)
            EnrollmentRequestService._mail_activation(db, req, raw)
            return True, ""

        # ── SIN cuenta: usuario nuevo con el NIP ──
        if not re.fullmatch(r"\d{4}", nip or ""):
            return False, _MSG_BAD_NIP

        savepoint = db.begin_nested()
        try:
            # El alias legado nace `graduate`: el mismo que `import_rows` le deja
            # a una cuenta que ya existía (`_sync_graduate_roles`).
            from itcj2.apps.titulatec.services.import_service import GRADUATE_ROLE
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

            # `commit=False`: `import_rows` solo hace `flush` y esta función es
            # dueña única de su transacción (Finding 2, ronda 1 de revisión).
            # Por lo mismo, el caché de authz de los roles que deja lo tira ESTA
            # función después de su commit, con los pares del summary.
            summary = ImportService.import_rows(
                db, cohort,
                [{"control_number": control, "full_name": full_name, "email": None,
                  "program_id": resolved_program_id, "modality_id": None}],
                actor_id=actor_id, source="enrollment_request",
                repair_credentials=False, commit=False,
            )
            proc = (db.query(TitulationProcess)
                    .filter_by(student_id=user.id, cohort_id=req.cohort_id).first())
            if proc is None:
                savepoint.rollback()
                return False, _MSG_NO_PROCESS

            # El perfil de un usuario recién creado sí se llena: es lo único que
            # se sabe de él y no pisa nada de nadie.
            StudentProfileService.set_fields(
                db, user.id,
                contact_email=req.contact_email, phone=req.phone,
                has_efirma=req.has_efirma, program_text=req.program_text,
                program_id=resolved_program_id,
            )
            req.status = "converted"
            req.program_id = resolved_program_id
            req.reviewed_by_id = actor_id
            req.reviewed_at = now
            req.converted_process_id = proc.id
            db.add(ProcessEvent(
                process_id=proc.id, actor_id=actor_id,
                event_type="enrollment_self_service", phase_number=0,
                # Se muestra en el expediente: aquí NO va el NIP.
                payload={"request_id": req.id, "folio": proc.folio,
                         "preexisting_process": False, "reviewed": True,
                         "activation": "nip_personal_email"},
            ))
            folio = proc.folio
            savepoint.commit()
        except Exception:
            if savepoint.is_active:
                savepoint.rollback()
            raise
        db.commit()
        # Después del commit: antes, una lectura concurrente repoblaría el caché
        # de authz con los roles de antes de aprobar.
        ImportService.invalidate_authz((summary or {}).get("authz_touched"))
        TitulaTecEmailHelper.send_enrollment_approved(db, req, user, nip=nip)
        return True, folio

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
        `import_rows`: ventana de la convocatoria, formato de los datos, que la
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

        # La ventana se revisa sobre la convocatoria GUARDADA en la solicitud: el
        # periodo va dentro del folio y de la ruta en disco.
        cohort = db.get(Cohort, req.cohort_id)
        if cohort is None or not CohortService.is_public_enrollment_open(cohort):
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

        Aplica desde `pending_review`, `approved` (cancela una liga en camino) y
        el legado. La liga muere en BD y en Redis; el motivo se manda al correo
        personal después del commit. El índice parcial deja volver a intentar.

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
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest

        req = db.get(EnrollmentRequest, req_id)
        if req is None:
            return False, _MSG_GONE
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _REQUEST_LOCK_NS, "key": int(req.id)})
        db.refresh(req)
        if req.status != "approved":
            return False, _MSG_ONLY_APPROVED

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
        muy pronto, ventana cerrada, liga vencida y la falta del claro en Redis
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
        if cohort is None or not CohortService.is_public_enrollment_open(cohort):
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
    def _issue_activation(req) -> str:
        """Emite (o rota) la liga de activación de `req`. Devuelve el claro.

        Solo sella la fila; el llamador fija el contador, commitea, cachea el
        claro y manda (`_mail_activation`), en ese orden. `verify_sent_at` y
        `verified_at` vuelven a NULL: "enviada" y "abierta" hablan de la liga
        vigente, no de una anterior.
        """
        raw = secrets.token_urlsafe(32)
        req.verify_token_hash = _sha256(raw)
        req.verify_expires_at = datetime.now() + timedelta(hours=VERIFY_TTL_HOURS)
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
          `sent` (liga enviada), `converted` (inscritas), `rejected`. Mismo alcance
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

        counts = {"total": 0, "review": 0, "sent": 0, "converted": 0, "rejected": 0}
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
                               "sent": 0, "converted": 0, "rejected": 0}
            bucket = years[year]
            bucket["total"] += 1
            bucket[_STATUS_GROUP.get(status, "review")] += 1

        by_year = sorted(
            years.values(),
            key=lambda y: (0, -int(y["year"])) if y["year"] != "Sin año" else (1, 0),
        )
        year_max = max((y["total"] for y in by_year), default=0)
        return {"counts": counts, "by_year": by_year, "year_max": year_max}
