"""Invitaciones: QR multiuso (5 min) e invitación manual por correo (48 h, un uso).

Del token de invitación solo se guarda el sha256; ni el token ni el NIP se
escriben jamás en logs ni en la bitácora.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta

import jwt

from itcj2.apps.prorrogas_tec.models.invitation import ProrrogaInvitation, ProrrogaJoin
from itcj2.apps.prorrogas_tec.services import notify
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.events import log_event
from itcj2.apps.prorrogas_tec.services.identity import institutional_email, normalize_control
from itcj2.config import get_settings
from itcj2.core.models.program import Program
from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.services.authz_service import grant_role
from itcj2.core.services.student_profile_service import StudentProfileService
from itcj2.core.utils.email_tools import is_valid_email, normalize_email
from itcj2.core.utils.security import hash_nip
from itcj2.core.utils.timezone import db_now

APP_KEY = "prorrogas_tec"
QR_TTL = timedelta(minutes=5)
INVITATION_TTL = timedelta(hours=48)
QR_PURPOSE = "prorrogas_join"
_NIP = re.compile(r"\d{4}")


def _sha(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


# --- QR -------------------------------------------------------------------

def issue_qr(secretary_id: int, *, now: datetime | None = None) -> dict:
    now = now or db_now()
    exp = now + QR_TTL
    token = jwt.encode({"p": QR_PURPOSE, "by": secretary_id, "exp": int(exp.timestamp()),
                        "jti": uuid.uuid4().hex}, get_settings().SECRET_KEY, algorithm="HS256")
    return {"token": token, "path": f"/prorrogas/unirse?t={token}", "expires_at": exp.isoformat()}


def read_qr(token: str, *, now: datetime | None = None) -> int:
    now = now or db_now()
    try:  # el vencimiento lo decide el reloj inyectado, no el de PyJWT
        claims = jwt.decode(token, get_settings().SECRET_KEY, algorithms=["HS256"],
                            options={"verify_exp": False, "require": ["exp", "p", "by"]})
        if claims["p"] != QR_PURPOSE:
            raise jwt.InvalidTokenError("propósito")
        by, exp = int(claims["by"]), float(claims["exp"])
    except (jwt.InvalidTokenError, TypeError, ValueError):
        raise ServiceError("qr_invalido", "El código QR no es válido. Pide uno nuevo.", status=400)
    if now.timestamp() >= exp:
        raise ServiceError("qr_expirado", "El código QR venció. Pide uno nuevo.", status=410)
    return by


# --- Alta -----------------------------------------------------------------

def _control(raw: str) -> str:
    try:
        return normalize_control(raw)
    except ValueError:
        raise ServiceError("control_invalido", "Número de control inválido.", status=400)


def _user_by_control(db, control: str) -> User | None:
    return db.query(User).filter(User.control_number == control).first()


def lookup(db, raw_control: str) -> dict:
    control = _control(raw_control)
    user = _user_by_control(db, control)
    sugerido = institutional_email(control) or (normalize_email(user.email) if user else None)
    return {
        "control_number": control,
        "existe": user is not None,
        "nombre": " ".join(p for p in (user.first_name, user.last_name, user.middle_name) if p) if user else None,
        "correo_sugerido": sugerido,
        "requiere_datos": user is None,
        "requiere_correo": sugerido is None,
    }


def invite(db, *, raw_control, email, actor_id, nombres=None, apellido_paterno=None,
           apellido_materno=None, program_id=None, now=None) -> tuple[ProrrogaInvitation, str]:
    now = now or db_now()
    control = _control(raw_control)
    user = _user_by_control(db, control)
    correo = normalize_email(email) or institutional_email(control) or (normalize_email(user.email) if user else None)
    if not correo:
        raise ServiceError("correo_requerido", "Captura el correo de la persona.", status=400)
    if not is_valid_email(correo):
        raise ServiceError("correo_invalido", "El correo no es válido.", status=400)

    created = user is None
    if created:
        nombres, ap_pat = (nombres or "").strip(), (apellido_paterno or "").strip()
        if not (nombres and ap_pat and program_id):
            raise ServiceError("datos_requeridos", "Faltan nombres, apellido paterno o carrera.", status=400)
        if db.get(Program, program_id) is None:
            raise ServiceError("carrera_invalida", "La carrera no existe.", status=400)
        role = db.query(Role).filter(Role.name == "student").first()
        user = User(first_name=nombres.upper(), last_name=ap_pat.upper(),
                    middle_name=(apellido_materno or "").strip().upper() or None,
                    control_number=control, email=correo, role_id=role.id if role else None, is_active=True)
        db.add(user)
        db.flush()
        StudentProfileService.set_fields(db, user.id, program_id=program_id)

    token = secrets.token_urlsafe(32)
    invitacion = ProrrogaInvitation(
        control_number=control, email=correo, user_id=user.id, token_sha256=_sha(token),
        expires_at=now + INVITATION_TTL, created_by_id=actor_id, user_created=created, created_at=now)
    db.add(invitacion)
    db.flush()
    link = f"{get_settings().DOMAIN}/prorrogas/unirse/invitacion/{token}"
    notify.send_email(template="invitacion.html", context={"link": link},
                      subject="Invitación al módulo de Prórrogas", to=correo, link=link)
    log_event(db, event_type="invitacion_enviada", actor_id=actor_id,
              payload={"invitation_id": invitacion.id, "control_number": control})
    db.commit()
    return invitacion, token


# --- Uso ------------------------------------------------------------------

def invitation_for_token(db, raw_token: str) -> ProrrogaInvitation | None:
    return db.query(ProrrogaInvitation).filter(ProrrogaInvitation.token_sha256 == _sha(raw_token)).first()


def _usable(db, raw_token: str, now: datetime, *, lock: bool = False) -> ProrrogaInvitation:
    q = db.query(ProrrogaInvitation).filter(ProrrogaInvitation.token_sha256 == _sha(raw_token))
    invitacion = (q.with_for_update() if lock else q).first()
    if invitacion is None:
        raise ServiceError("invitacion_invalida", "La invitación no es válida.", status=404)
    if invitacion.used_at is not None:
        raise ServiceError("invitacion_usada", "Esta invitación ya se usó.", status=409)
    if invitacion.expires_at is None or now >= invitacion.expires_at:
        raise ServiceError("invitacion_expirada", "La invitación venció. Pide otra.", status=410)
    return invitacion


def join(db, user_id: int, *, via: str, issued_by_id: int | None, invitation_id: int | None = None,
         now: datetime | None = None) -> ProrrogaJoin:
    row = ProrrogaJoin(user_id=user_id, via=via, invitation_id=invitation_id,
                       issued_by_id=issued_by_id, joined_at=now or db_now())
    db.add(row)
    db.flush()
    grant_role(db, user_id, APP_KEY, "student")  # commitea la unión y todo lo pendiente
    db.commit()
    return row


def consume_invitation(db, raw_token: str, *, user_id: int, now: datetime | None = None) -> ProrrogaJoin:
    now = now or db_now()
    invitacion = _usable(db, raw_token, now, lock=True)
    if invitacion.user_id != user_id:
        db.rollback()  # suelta el candado; la invitación sigue sin usarse
        raise ServiceError("invitacion_de_otra_cuenta", "Esta invitación es de otra cuenta.", status=403)
    invitacion.used_at = now
    return join(db, user_id, via="invitacion", issued_by_id=invitacion.created_by_id,
                invitation_id=invitacion.id, now=now)


def set_initial_nip(db, raw_token: str, nip: str, nip2: str) -> None:
    invitacion = _usable(db, raw_token, db_now())
    user = invitacion.user
    if user.password_hash:
        raise ServiceError("cuenta_con_nip", "La cuenta ya tiene NIP.", status=409)
    if not _NIP.fullmatch(nip or ""):
        raise ServiceError("nip_invalido", "El NIP debe tener 4 dígitos.", status=400)
    if nip != nip2:
        raise ServiceError("nip_no_coincide", "Los NIP no coinciden.", status=400)
    user.password_hash = hash_nip(nip)
    db.commit()


# --- Resumen --------------------------------------------------------------

def today_summary(db, *, now: datetime | None = None) -> dict:
    now = now or db_now()
    ini = now.replace(hour=0, minute=0, second=0, microsecond=0)
    fin = ini + timedelta(days=1)
    invs = db.query(ProrrogaInvitation).filter(ProrrogaInvitation.created_at >= ini,
                                               ProrrogaInvitation.created_at < fin)
    return {
        "se_unieron_hoy": db.query(ProrrogaJoin).filter(ProrrogaJoin.joined_at >= ini,
                                                        ProrrogaJoin.joined_at < fin).count(),
        "invitaciones_hoy": invs.count(),
        "ultimas": [{"correo": i.email, "hora": i.created_at.strftime("%H:%M")}
                    for i in invs.order_by(ProrrogaInvitation.created_at.desc(), ProrrogaInvitation.id.desc()).limit(3)],
    }
