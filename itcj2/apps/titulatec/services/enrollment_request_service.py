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
import logging
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from itcj2.apps.titulatec.services.import_service import CONTROL_NUMBER_RE  # noqa: F401

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
