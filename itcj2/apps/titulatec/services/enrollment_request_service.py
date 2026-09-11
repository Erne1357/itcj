"""Solicitudes de auto-inscripción a una convocatoria de titulación.

Diseño: `docs/superpowers/specs/2026-09-07-titulatec-survey-campaign-design.md`
(§6.8 y §6.9). Aquí viven las constantes de inscripción del contrato.

CANJE E7, DELIBERADO. La BD guarda SOLO `sha256(token)`, así que de ella no se
recupera el original. Pero §6.8 exige que el reenvío **no rote** el token —rotarlo
dejaría a un extraño invalidar la liga pendiente de un solicitante real—, y sin el
claro no hay nada que reenviar. Por eso el texto en claro vive en Redis durante
`VERIFY_TTL_HOURS` bajo `tt:enroll:tok:<sha256>`: es el precio de la no-rotación.
Es una credencial en claro en una caché compartida, con vida acotada a la ventana
del token; cuando esa copia no está, `_send_verify` falla CERRADO (devuelve
`False`) en vez de emitir uno nuevo.

RULING R5 (revisión de la Tarea 19, sobre un aviso que dejó la Tarea 18): el
destinatario del token de verificación SIEMPRE sale de
`TitulaTecEmailHelper.verify_recipient(db, req)`, nunca se arma a mano en este
módulo con `student_email(user)` o con `data['contact_email']`. Es la única forma
de que sea IMPOSIBLE que la liga de un `known` termine en el correo que un
desconocido escribió por él — exactamente el hueco que D17 existe para cerrar.
Tanto `create()` como `_send_verify()` pasan por ahí; ver
`tests/fastapi/titulatec/test_enrollment_request_service.py` para las pruebas que
lo fijan.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE

logger = logging.getLogger("itcj2.apps.titulatec.enrollment_request")

STATUSES = ("unverified", "verified", "pending_review", "approved", "rejected", "converted")

VERIFY_TTL_HOURS = 48
CONTACT_TTL_HOURS = 168          # 7 días; no bloquea la inscripción (D17)
MAX_VERIFY_SENDS = 3
MIN_SECONDS_BETWEEN_SENDS = 300
MAX_PUBLIC_BODY_BYTES = 256 * 1024

# Mismo origen que `MaintEmailHelper._BASE_URL`: las ligas de correo salen de
# aquí, nunca del `Host` de la petición (que el cliente controla).
PUBLIC_BASE_URL = "https://enlinea.cdjuarez.tecnm.mx"

# Prefijo de Redis donde vive el TEXTO CLARO del token mientras dura su ventana.
# La BD guarda SOLO el sha256 (E7). Sin esta copia efímera, «el reenvío no rota
# el token» (§6.8) sería irrealizable: de un sha256 no se recupera el original.
# La clave es el propio hash, así que una entrada rancia jamás puede aplicarse a
# otra solicitud.
_TOKEN_CACHE_PREFIX = "tt:enroll:tok:"

# Namespace del advisory lock que serializa `verify()` por SOLICITUD (Ronda de
# arreglos 1, Important 2). Mismo mecanismo que `_FOLIO_LOCK_NS` de
# `import_service.py` (transacción-scoped, lo único compatible con PgBouncer
# en modo transaction) pero un valor DISTINTO: comparten proceso pero no deben
# compartir namespace, o un `key` que coincida por accidente (un id de
# cohorte y un id de solicitud del mismo número) se bloquearía entre sí sin
# necesidad.
_VERIFY_LOCK_NS = 0x7456  # "tV"


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


def _verify_link(raw: str) -> str:
    return f"{PUBLIC_BASE_URL}/titulatec/inscripcion/verificar?t={raw}"


def _contact_link(raw: str) -> str:
    return f"{PUBLIC_BASE_URL}/titulatec/inscripcion/correo?t={raw}"


def _hash_ip(ip: str | None) -> str | None:
    """`sha256(ip + SECRET_KEY)`. La IP en claro nunca se guarda (§8.2)."""
    if not ip:
        return None
    from itcj2.config import get_settings
    return hashlib.sha256((ip + get_settings().SECRET_KEY).encode("utf-8")).hexdigest()


class EnrollmentRequestService:
    """Alta, verificación y reenvío de solicitudes de inscripción."""

    @staticmethod
    def create(db: Session, cohort, data: dict, *, client_ip: str | None):
        """Alta de solicitud. Devuelve `(req|None, outcome)`.

        `outcome ∈ 'created' | 'existing_request' | 'existing_process'`. Las tres
        ramas producen la MISMA respuesta HTTP (E8): lo que las distingue viaja
        por correo, a un buzón cuya posesión ya está probada. El llamador (la
        ruta) ignora a propósito el valor de retorno para no reintroducir esa
        distinción en la respuesta.
        """
        from itcj2.core.models.user import User
        from itcj2.apps.titulatec.models import EnrollmentRequest, TitulationProcess
        from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

        control = (data.get("control_number") or "").strip()
        user = db.query(User).filter_by(control_number=control).first()

        # (a) Ya tiene proceso vivo en CUALQUIER convocatoria (D5). No se crea
        #     fila: se le avisa a su buzón institucional en cuál está.
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

        # (b) Ya hay una solicitud viva en esta convocatoria: se reenvía al buzón
        #     guardado, con el presupuesto de `_send_verify`. Esta rama se
        #     dispara con SOLO el número de control, que cualquiera puede
        #     teclear: es la garantía de no-rotación de `_send_verify` —y de que
        #     su destinatario sale de `verify_recipient`, nunca del cable— la
        #     que impide que un extraño la use para invalidar o redirigir la
        #     liga pendiente de otra persona.
        live = (db.query(EnrollmentRequest)
                .filter(EnrollmentRequest.cohort_id == cohort.id,
                        EnrollmentRequest.control_number == control,
                        EnrollmentRequest.status.in_(
                            ("unverified", "verified", "pending_review")))
                .order_by(EnrollmentRequest.id.desc())
                .first())
        if live is not None:
            EnrollmentRequestService._send_verify(db, live)
            return live, "existing_request"

        kind = "known" if user is not None else "unknown"
        raw = secrets.token_urlsafe(32)

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
            kind=kind,
            status="unverified",
            verify_token_hash=_sha256(raw),
            verify_expires_at=datetime.now() + timedelta(hours=VERIFY_TTL_HOURS),
            verify_send_count=0,
            created_ip_hash=_hash_ip(client_ip),
        )
        db.add(req)
        db.flush()
        _token_cache_put(raw)

        # RULING R5: el destinatario SIEMPRE sale de `verify_recipient`, que
        # para 'known' vuelve a resolver el institucional contra la BD (no
        # confía en el `user` de arriba ni en `data`) y para 'unknown' devuelve
        # `req.contact_email`. Si no hay a quién mandarlo, no se manda nada — la
        # solicitud igual queda escrita (§9: "un fallo de correo no puede tumbar
        # una inscripción").
        to = TitulaTecEmailHelper.verify_recipient(db, req)
        req.verify_sent_to = to or None
        if to and TitulaTecEmailHelper.send_verify_enrollment(
                db, req, to=to, link=_verify_link(raw)):
            req.verify_sent_at = datetime.now()
        req.verify_send_count = 1

        # Segunda liga, SOLO para el conocido: confirma su correo personal (D17).
        # Para el desconocido sería redundante — el token ya fue a ese buzón.
        if kind == "known":
            craw = secrets.token_urlsafe(32)
            req.contact_token_hash = _sha256(craw)
            req.contact_expires_at = datetime.now() + timedelta(hours=CONTACT_TTL_HOURS)
            TitulaTecEmailHelper.send_confirm_contact(
                db, req, to=req.contact_email, link=_contact_link(craw))

        db.commit()
        return req, "created"

    @staticmethod
    def _send_verify(db: Session, req) -> bool:
        """Reenvía el token de `req` respetando el presupuesto por solicitud.

        Presupuesto: `MAX_VERIFY_SENDS` envíos en total y >= `MIN_SECONDS_BETWEEN_SENDS`
        entre uno y otro, contabilizados en `verify_send_count` / `verify_sent_at`.

        NUNCA rota `verify_token_hash` (§6.8): rotarlo dejaría a un extraño
        invalidar la liga pendiente de un solicitante real con solo teclear su
        número de control. Dos guardas fallan CERRADO sin tocar el presupuesto
        ni la ventana: sin el texto claro en Redis, y sin un destinatario que
        `verify_recipient` pueda resolver (RULING R5 — nunca se cae a
        `req.contact_email` ni a `req.verify_sent_to` como sustituto).
        """
        from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

        if (req.verify_send_count or 0) >= MAX_VERIFY_SENDS:
            return False
        if req.verify_sent_at is not None:
            elapsed = (datetime.now() - req.verify_sent_at).total_seconds()
            if elapsed < MIN_SECONDS_BETWEEN_SENDS:
                return False

        raw = _token_cache_get(req.verify_token_hash or "")
        if raw is None:
            # §6.8: sin el claro NO hay reenvío. Rotar el token dejaría a un
            # extraño invalidar la liga pendiente de un solicitante real, así que
            # se falla cerrado: no se consume envío ni se extiende la ventana.
            return False

        to = TitulaTecEmailHelper.verify_recipient(db, req)
        if not to:
            # RULING R5: mismo criterio que arriba. `req.verify_sent_to` puede
            # venir vacío (p. ej. si la resolución inicial ya falló) y
            # `req.contact_email` NUNCA es un sustituto válido para un
            # `known` — es exactamente la fuga que D17 existe para cerrar. Se
            # falla cerrado sin tocar el presupuesto, igual que con el claro
            # ausente.
            return False

        _token_cache_put(raw)
        req.verify_expires_at = datetime.now() + timedelta(hours=VERIFY_TTL_HOURS)
        req.verify_send_count = (req.verify_send_count or 0) + 1
        req.verify_sent_at = datetime.now()
        req.verify_sent_to = to
        db.commit()
        TitulaTecEmailHelper.send_verify_enrollment(db, req, to=to, link=_verify_link(raw))
        return True

    @staticmethod
    def verify(db: Session, token: str):
        """Abre la liga de verificación. Devuelve `(req|None, outcome)`.

        `outcome ∈ 'converted' | 'pending_review' | 'already_converted' |
        'already_pending' | 'invalid' | 'expired'`.

        ES IDEMPOTENTE a propósito: Outlook Safe Links y los escáneres de correo
        corporativos prefetchean la liga en cuanto llega. Si el token se marcara
        "usado" y la segunda visita diera error, la persona vería un fallo
        estando ya inscrita y gastaría sus 3 reenvíos intentando arreglarlo.

        DESVIACIÓN DEL BORRADOR DEL BRIEF: la comparación decisiva usa
        `hmac.compare_digest` de la librería estándar, DIRECTO — no existe un
        `_compare` en este módulo. La Tarea 19 lo omitió a propósito (no estaba
        en su "Produces" y no tenía un solo test que lo ejerciera; ver su
        reporte). Es una credencial al portador: un `==` de Python sale en el
        primer byte distinto, así que el tiempo de respuesta filtraría cuántos
        bytes acertó quien lo intenta. `hmac.compare_digest` tarda lo mismo
        acierte o falle. `test_verify_usa_comparacion_en_tiempo_constante`
        (`tests/fastapi/titulatec/test_enrollment_verify.py`) fija esto leyendo
        la fuente: un comparador en tiempo constante calcula la MISMA igualdad
        que `==` (nada más deja de filtrarla por temporización), así que ningún
        test de comportamiento puede detectar una regresión aquí.

        RONDA DE ARREGLOS 1, IMPORTANT 2. El único gate era antes un `SELECT`
        plano (`if req.status == "converted": ...`), sin lock: dos peticiones
        concurrentes con el MISMO token —el prefetch de un escáner de correo
        corporativo en paralelo con el clic humano es el caso NORMAL, no el
        raro— podían las dos pasar el gate antes de que ninguna escribiera
        "converted", duplicando el `ProcessEvent` y el correo de
        `send_enrollment_done` (reproducido por el revisor llamando a
        `_convert` dos veces seguidas). Se serializa por `req.id` con
        `pg_advisory_xact_lock`, mismo mecanismo que usa `import_rows` para los
        folios. El `db.refresh(req)` INMEDIATAMENTE DESPUÉS es la mitad que
        hace que el lock sirva de algo: bajo READ COMMITTED, una transacción
        que esperó el lock puede seguir teniendo en memoria el `req.status` de
        ANTES de esperarlo —adquirir el lock no hace que SQLAlchemy relea el
        objeto solo porque Postgres se lo permitió—, así que sin el refresh la
        segunda pasada evaluaría el `if` de abajo contra un valor viejo y
        duplicaría igual. Ver `test_verify_toma_lock_advisory_por_solicitud_y_refresca_antes_de_leer_status`
        (estructural: fija la presencia Y el orden de las tres piezas, porque
        tampoco esto es detectable por comportamiento dentro de una sola
        sesión — ver el reporte de la Tarea 20 para qué SÍ y qué NO se pudo
        probar de la concurrencia real).
        """
        from itcj2.apps.titulatec.models import EnrollmentRequest

        if not token:
            return None, "invalid"
        digest = _sha256(token)
        # La búsqueda por índice es lo que la hace O(1); la comparación en
        # tiempo constante es la que decide (E7).
        req = (db.query(EnrollmentRequest)
               .filter(EnrollmentRequest.verify_token_hash == digest).first())
        if req is None or not hmac.compare_digest(req.verify_token_hash or "", digest):
            return None, "invalid"

        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _VERIFY_LOCK_NS, "key": int(req.id)})
        db.refresh(req)

        if req.status == "converted":
            return req, "already_converted"
        if req.status == "pending_review":
            return req, "already_pending"
        if req.status == "rejected":
            return req, "invalid"
        if req.verify_expires_at is not None and req.verify_expires_at < datetime.now():
            return req, "expired"

        if req.verified_at is None:
            req.verified_at = datetime.now()

        if req.kind == "unknown":
            req.status = "pending_review"
            db.commit()
            return req, "pending_review"

        req.status = "verified"
        ok, detail = EnrollmentRequestService._convert(db, req)
        if not ok:
            req.status = "pending_review"
            req.review_note = detail
            db.commit()
            return req, "pending_review"
        db.commit()
        return req, "converted"

    @staticmethod
    def _convert(db: Session, req):
        """Convierte una solicitud verificada en proceso (§6.9).

        Devuelve `(ok, detalle)`; en éxito `detalle` es el folio. Todo lo que
        puede haber cambiado en las 48 h se revisa ANTES de `import_rows`.

        RONDA DE ARREGLOS 1, IMPORTANT 1 — CORRECCIÓN SOBRE EL DOCSTRING
        ORIGINAL. La versión anterior de este docstring decía «`import_rows`
        commitea por su cuenta: abortar después no revierte nada» y, dos
        líneas más abajo, «`_convert` es dueño de su propia transacción» — las
        dos afirmaciones NO podían ser ciertas a la vez, y la llamada de abajo
        de verdad omitía `commit=False`. El revisor lo reprodujo: un fallo real
        en `StudentProfileService.set_fields` (la única escritura entre el
        `import_rows` de abajo y el final) dejaba un `User` y un
        `TitulationProcess` REALES y COMMITEADOS, con la solicitud congelada en
        `status="verified"` para siempre —un estado fuera del contrato de seis
        salidas— y sin bandeja en `pages/admin.py` que lo expusiera. Con
        `commit=False`, `import_rows` solo hace `flush()` (`import_service.py`,
        parámetro `commit`): AHORA SÍ, `_convert` es el dueño único de su
        transacción — nada de lo que se ejecuta aquí commitea por su cuenta, y
        el commit final (`verify()`, líneas de arriba) cubre la operación
        entera. Un fallo en cualquier punto —antes, DENTRO de `import_rows`, o
        después— se deshace completo con el `rollback()` de
        `enroll_verify` (`pages/public.py`). Ver
        `test_fallo_entre_import_rows_y_el_commit_final_no_deja_usuario_ni_proceso_huerfanos`.
        """
        from itcj2.core.models.user import User
        from itcj2.core.services.student_profile_service import StudentProfileService
        from itcj2.apps.titulatec.models import Cohort, ProcessEvent, TitulationProcess
        from itcj2.apps.titulatec.services.cohort_service import CohortService
        from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper
        from itcj2.apps.titulatec.services.import_service import ImportService

        # 1. La ventana se revisa sobre la convocatoria GUARDADA en la solicitud.
        #    Re-derivarla podría mandar al solicitante a otro periodo del que se
        #    le mostró, y el periodo va dentro del folio y de la ruta en disco.
        cohort = db.get(Cohort, req.cohort_id)
        if cohort is None or not CohortService.is_public_enrollment_open(cohort):
            return False, "La convocatoria se cerró antes de que confirmaras."

        control = (req.control_number or "").strip()
        full_name = " ".join(
            x for x in (req.last_name, req.middle_name, req.first_name) if x).strip()

        # 3. Las dos causas por las que `import_rows` salta filas EN SILENCIO.
        if not CONTROL_NUMBER_RE.fullmatch(control) or not full_name:
            return False, "Tus datos necesitan revisión manual."

        user = db.query(User).filter_by(control_number=control).first()
        ya_existia = False
        if user is not None:
            # 2. D5 EXCEPTUANDO la convocatoria de esta solicitud: D5 impide
            #    entrar a una SEGUNDA convocatoria, no atender la propia.
            otro = (db.query(TitulationProcess)
                    .filter(TitulationProcess.student_id == user.id,
                            TitulationProcess.cohort_id != req.cohort_id,
                            TitulationProcess.status.in_(("active", "on_hold")))
                    .first())
            if otro is not None:
                return False, "Ya tienes un proceso de titulación en otra convocatoria."

            # 4. `import_rows` le pondría de contraseña su número de control, que
            #    es dato público. Bajo D15 la fija Servicios Escolares con un NIP.
            if not user.password_hash:
                return False, ("Tu cuenta no tiene contraseña; Servicios Escolares "
                               "la dará de alta.")

            ya_existia = (db.query(TitulationProcess)
                          .filter_by(student_id=user.id, cohort_id=req.cohort_id)
                          .first()) is not None

        ImportService.import_rows(
            db, cohort,
            [{"control_number": control, "full_name": full_name, "email": None,
              "program_id": req.program_id, "modality_id": None}],
            actor_id=None, source="self_service", repair_credentials=False,
            commit=False,
        )

        # NO se ramifica sobre `processes_created`: si un CSV del personal creó
        # el proceso mientras la persona no daba clic, la conversión es igual de
        # exitosa. Solo la AUSENCIA de proceso es un error.
        user = db.query(User).filter_by(control_number=control).first()
        proc = (db.query(TitulationProcess)
                .filter_by(student_id=user.id, cohort_id=req.cohort_id).first()
                if user is not None else None)
        if proc is None:
            return False, "No pudimos crear tu proceso; Servicios Escolares lo revisará."

        # `contact_email_verified_at` sigue NULL hasta que abra su segunda liga (D17).
        StudentProfileService.set_fields(
            db, user.id,
            contact_email=req.contact_email, phone=req.phone,
            has_efirma=req.has_efirma, program_text=req.program_text,
        )

        req.status = "converted"
        req.converted_process_id = proc.id
        db.add(ProcessEvent(
            process_id=proc.id, actor_id=None,
            event_type="enrollment_self_service", phase_number=0,
            payload={"request_id": req.id, "folio": proc.folio,
                     "preexisting_process": ya_existia},
        ))
        TitulaTecEmailHelper.send_enrollment_done(db, req, proc)
        return True, proc.folio

    @staticmethod
    def resend(db: Session, control_number: str, contact_email: str) -> str:
        """Reenvía la liga. Devuelve `'sent'` o `'noop'`.

        `'noop'` cubre TODO lo que no manda correo: no casa, tope alcanzado,
        muy pronto, ventana cerrada, estado terminal y la falta del claro en el
        caché (§6.8: sin él NO se rota, se falla cerrado). La respuesta HTTP es
        la misma en todos los casos, así que el endpoint no es oráculo de
        existencia; darle tarjeta propia a la falta de caché lo convertiría en
        uno.

        La llave es (control_number, contact_email) y nunca el `id`: el `id` es
        un BigInteger secuencial y cualquiera enumeraría 1..N para disparar
        correos a buzones ajenos desde el buzón del instituto.
        """
        from sqlalchemy import func
        from itcj2.core.utils.email_tools import normalize_email
        from itcj2.apps.titulatec.models import Cohort, EnrollmentRequest
        from itcj2.apps.titulatec.services.cohort_service import CohortService

        control = (control_number or "").strip()
        email = normalize_email(contact_email) or ""
        if not control or not email:
            return "noop"

        # `converted` y `rejected` no entran al filtro: se rechazan SIN consumir
        # un envío, que es justo lo que pide §6.8.
        req = (db.query(EnrollmentRequest)
               .filter(EnrollmentRequest.control_number == control,
                       func.lower(EnrollmentRequest.contact_email) == email.lower(),
                       EnrollmentRequest.status.in_(("unverified", "verified")))
               .order_by(EnrollmentRequest.id.desc())
               .first())
        if req is None:
            return "noop"

        cohort = db.get(Cohort, req.cohort_id)
        if cohort is None or not CohortService.is_public_enrollment_open(cohort):
            return "noop"

        if (req.verify_send_count or 0) >= MAX_VERIFY_SENDS:
            # Presupuesto agotado. Un `known` cuyo institucional no responde pasa
            # a la bandeja: el token NUNCA se manda al correo personal (D17).
            if req.kind == "known" and req.verified_at is None:
                req.status = "pending_review"
                req.review_note = "El correo institucional no respondió tras 3 envíos."
                db.commit()
            return "noop"

        return "sent" if EnrollmentRequestService._send_verify(db, req) else "noop"

    @staticmethod
    def confirm_contact(db: Session, token: str) -> bool:
        """Confirma el correo PERSONAL declarado (D17).

        Es independiente de la inscripción: no la bloquea ni cambia su estado.
        Solo se emite para `kind='known'`, cuyo usuario ya existe en
        `core_users`; para el desconocido el token de verificación ya fue a ese
        mismo buzón y una segunda liga sería redundante.

        `core_users.email` NO se toca (D12): el correo personal vive en
        `core_student_profile`.

        IDEMPOTENTE A PROPÓSITO, mismo criterio que `verify()` (arriba en este
        módulo): esta liga también es un GET plano que un escáner de correo
        corporativo puede prefetchear antes del clic humano, y `set_fields` /
        `mark_contact_verified` son upserts inocuos de repetir (mismo valor
        cada vez). NO se invalida `contact_token_hash` tras un uso exitoso: la
        guarda real contra una liga vieja es `contact_expires_at`, de abajo.

        RULING R1 (Tarea 21): la comparación decisiva usa `hmac.compare_digest`
        de la librería estándar, DIRECTO — no existe un `_compare` en este
        módulo (se omitió a propósito en la Tarea 19; ver el docstring de
        `verify()`, arriba, para el porqué completo). Mismo motivo aquí: el
        token es una credencial al portador y un `==` filtraría por temporización
        cuántos bytes acertó quien lo intenta.
        """
        from itcj2.core.models.user import User
        from itcj2.core.services.student_profile_service import StudentProfileService
        from itcj2.apps.titulatec.models import EnrollmentRequest

        if not token:
            return False
        digest = _sha256(token)
        # Búsqueda por índice (O(1)); la comparación en tiempo constante decide.
        req = (db.query(EnrollmentRequest)
               .filter(EnrollmentRequest.contact_token_hash == digest).first())
        if req is None or not hmac.compare_digest(req.contact_token_hash or "", digest):
            return False
        if req.contact_expires_at is not None and req.contact_expires_at < datetime.now():
            return False

        user = db.query(User).filter_by(control_number=req.control_number).first()
        if user is None:
            return False

        # Ninguno de los dos commitea (docstring de `StudentProfileService`):
        # esta llamada es dueña de su propia transacción y la única que commitea.
        StudentProfileService.set_fields(db, user.id, contact_email=req.contact_email)
        StudentProfileService.mark_contact_verified(db, user.id)
        db.commit()
        return True

    @staticmethod
    def approve(db: Session, req_id: int, *, nip: str, program_id: int | None,
                actor_id: int):
        """Aprueba una solicitud de bandeja (§6.10). Devuelve `(ok, detalle)`.

        En éxito `detalle` es el folio; en fallo, el motivo que ve el oficial.
        EL NIP NUNCA SALE DE AQUÍ: no se registra en logs, no viaja en
        `X-Tt-Error` y no entra al payload del `ProcessEvent`. Es la contraseña
        del alumno (D15), y `detalle` se emite tal cual en una cabecera.
        """
        import re

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
            return False, "La solicitud ya no existe."
        if req.status in ("converted", "rejected"):
            return False, "Esa solicitud ya se resolvió."
        if not re.fullmatch(r"\d{4}", nip or ""):
            return False, "El NIP debe ser exactamente 4 dígitos."

        cohort = db.get(Cohort, req.cohort_id)
        if cohort is None:
            return False, "La convocatoria ya no existe."
        if not CohortService.is_public_enrollment_open(cohort):
            return False, "Esa convocatoria está cerrada; abre su ventana primero."

        control = (req.control_number or "").strip()
        full_name = " ".join(
            x for x in (req.last_name, req.middle_name, req.first_name) if x).strip()
        if not CONTROL_NUMBER_RE.fullmatch(control) or not full_name:
            return False, "El número de control o el nombre no tienen formato válido."

        resolved_program_id = program_id if program_id else req.program_id
        user = db.query(User).filter_by(control_number=control).first()
        # Finding 3 (ronda 1 de revisión): si la persona YA tenía password_hash
        # (p. ej. de un CSV de otra convocatoria), ese NIP capturado aquí NO es
        # su contraseña — se preserva el hash existente (romperlo sería un
        # vector de secuestro de cuenta: el formulario público de inscripción
        # deja que cualquiera declare un número de control ajeno). Pero
        # entonces el correo de "acceso con NIP" mentiría, así que se rastrea
        # si de verdad se escribió la credencial para decidir qué correo mandar.
        credential_set = False
        if user is None:
            student_role = db.query(Role).filter_by(name="student").first()
            user = User(
                username=control, control_number=control,
                first_name=req.first_name, last_name=req.last_name,
                middle_name=req.middle_name or None,
                email=None,
                role_id=student_role.id if student_role else None,
                is_active=True, must_change_password=True,
            )
            user.password_hash = hash_nip(nip)   # nunca `set_initial_credential`
            credential_set = True
            db.add(user)
            db.flush()
        else:
            otro = (db.query(TitulationProcess)
                    .filter(TitulationProcess.student_id == user.id,
                            TitulationProcess.cohort_id != req.cohort_id,
                            TitulationProcess.status.in_(("active", "on_hold")))
                    .first())
            if otro is not None:
                return False, "Esa persona ya tiene un proceso en otra convocatoria."
            if not user.password_hash:
                user.password_hash = hash_nip(nip)
                credential_set = True
            user.must_change_password = True
            user.is_active = True
            db.flush()

        ya_existia = (db.query(TitulationProcess)
                      .filter_by(student_id=user.id, cohort_id=req.cohort_id)
                      .first()) is not None

        # Finding 2 (ronda 1 de revisión): `commit=False`, mismo arreglo que
        # `_convert` (ver su docstring, arriba) — sin esto `import_rows`
        # commitea por su cuenta ANTES de `StudentProfileService.set_fields` y
        # del resto de este método, y un fallo real ahí deja un `User`/
        # `TitulationProcess` huérfanos y ya commiteados. `approve` es dueña
        # única de su transacción; el rollback ante excepción lo hace la ruta
        # (`pages/requests_admin.py`), igual que `enroll_verify` hace por
        # `_convert`.
        ImportService.import_rows(
            db, cohort,
            [{"control_number": control, "full_name": full_name, "email": None,
              "program_id": resolved_program_id, "modality_id": None}],
            actor_id=actor_id, source="enrollment_request", repair_credentials=False,
            commit=False,
        )

        # Igual que §6.9: se busca el proceso, no se ramifica sobre el contador.
        proc = (db.query(TitulationProcess)
                .filter_by(student_id=user.id, cohort_id=req.cohort_id).first())
        if proc is None:
            return False, "No se pudo crear el proceso; revisa los datos de la solicitud."

        StudentProfileService.set_fields(
            db, user.id,
            contact_email=req.contact_email, phone=req.phone,
            has_efirma=req.has_efirma, program_text=req.program_text,
            program_id=resolved_program_id,
        )

        req.status = "converted"
        req.program_id = resolved_program_id
        req.reviewed_by_id = actor_id
        req.reviewed_at = datetime.now()
        req.converted_process_id = proc.id
        # El payload se muestra en el expediente: aquí NO va el NIP.
        db.add(ProcessEvent(
            process_id=proc.id, actor_id=actor_id,
            event_type="enrollment_self_service", phase_number=0,
            payload={"request_id": req.id, "folio": proc.folio,
                     "preexisting_process": ya_existia, "reviewed": True},
        ))
        db.commit()
        if credential_set:
            TitulaTecEmailHelper.send_enrollment_approved(db, req, user, nip=nip)
        else:
            # Finding 3: el hash existente se preservó — el NIP capturado aquí
            # NO abre esta cuenta. Mandar `send_enrollment_approved` de todas
            # formas prometería un acceso falso al correo PERSONAL (que además
            # puede ser el que escribió un desconocido, no la persona dueña de
            # la cuenta). Se avisa el folio al institucional en su lugar —
            # mismo correo que usa la conversión automática (`_convert`).
            TitulaTecEmailHelper.send_enrollment_done(db, req, proc)
        return True, proc.folio

    @staticmethod
    def reject(db: Session, req_id: int, *, note: str, actor_id: int) -> bool:
        """Rechaza con motivo obligatorio. El índice parcial deja re-intentar."""
        from itcj2.apps.titulatec.models import EnrollmentRequest
        from itcj2.apps.titulatec.services.email_helper import TitulaTecEmailHelper

        req = db.get(EnrollmentRequest, req_id)
        if req is None or req.status in ("converted", "rejected"):
            return False
        if not (note or "").strip():
            return False
        req.status = "rejected"
        req.review_note = note.strip()[:2000]
        req.reviewed_by_id = actor_id
        req.reviewed_at = datetime.now()
        db.commit()
        TitulaTecEmailHelper.send_enrollment_rejected(db, req)
        return True
