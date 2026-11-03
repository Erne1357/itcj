"""Resolución de un token del QR y bitácora de verificaciones del personal.

Invariante de la ruta pública (spec §6): un token vencido o no válido NO toca
datos personales. ``resolve`` devuelve ``student``/``photo`` en ``None`` para esos
estados y ``public_view`` no muestra nada si no hay alumno.
"""
import base64
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from itcj2.apps.credencial.models import CredentialPhoto
    from itcj2.core.models.user import User

logger = logging.getLogger(__name__)

Status = Literal["valid", "inactive", "expired", "invalid"]


@dataclass(frozen=True)
class VerificationResult:
    status: Status
    student: "User | None" = None
    photo: "CredentialPhoto | None" = None
    issued_at: datetime | None = None   # aware UTC


def display_name(user) -> str:
    """Orden de la credencial: Nombre Apellido paterno Apellido materno."""
    return " ".join(p for p in (user.first_name, user.last_name, user.middle_name) if p)


def program_label(db: Session, user_id: int) -> str | None:
    """Carrera del alumno. shortcut: core_programs.name crudo; la Tarea 4 lo cambia por program_display_name."""
    from itcj2.core.models.program import Program
    from itcj2.core.models.student_profile import StudentProfile

    return (
        db.query(Program.name)
        .join(StudentProfile, StudentProfile.program_id == Program.id)
        .filter(StudentProfile.user_id == user_id)
        .scalar()
    )


def _photo_data_uri(photo) -> str | None:
    """Foto incrustada; no existe endpoint público de foto. Sin archivo = sin foto, nunca 500."""
    from itcj2.config import get_settings
    from itcj2.core.utils.safe_paths import safe_join

    try:
        # shortcut: lee el archivo aqui; la Tarea 3 lo cambia por PhotoService.read_bytes.
        data = safe_join(get_settings().CREDENCIAL_PHOTO_PATH, photo.file_name).read_bytes()
    except Exception as e:
        logger.warning("credencial: foto ilegible user_id=%s (%s)", photo.user_id, type(e).__name__)
        return None
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


class VerificationService:
    @staticmethod
    def resolve(db: Session, token: str, now: datetime | None = None) -> VerificationResult:
        from itcj2.apps.credencial.models import CredentialPhoto
        from itcj2.apps.credencial.services.token_service import (
            CredentialTokenService, TokenExpired, TokenInvalid,
        )
        from itcj2.core.models.user import User

        try:
            claims = CredentialTokenService.parse(token, now=now)
        except TokenExpired:
            return VerificationResult("expired")
        except TokenInvalid:
            return VerificationResult("invalid")

        photo = db.query(CredentialPhoto).filter_by(ref=claims.ref).first()
        student = db.get(User, photo.user_id) if photo else None
        if student is None:
            return VerificationResult("invalid")
        return VerificationResult(
            "valid" if student.is_active else "inactive", student, photo, claims.issued_at,
        )

    @staticmethod
    def public_view(db: Session, result: VerificationResult) -> dict:
        """Datos personales que la página puede mostrar. Inactiva: nombre y foto, nada más."""
        if result.status not in ("valid", "inactive"):
            return {}
        view = {
            "name": display_name(result.student),
            "photo_uri": _photo_data_uri(result.photo),
        }
        if result.status == "valid":
            view["program"] = program_label(db, result.student.id)
        return view

    @staticmethod
    def record(db: Session, result: VerificationResult, verifier_id: int):
        from itcj2.apps.credencial.models import CredentialVerification
        from itcj2.core.utils.timezone import APP_TIMEZONE

        if result.status not in ("valid", "inactive"):
            raise ValueError("Solo se registran verificaciones de un token vigente")
        row = CredentialVerification(
            student_id=result.student.id,
            verifier_id=verifier_id,
            result=result.status,
            # Naive local, como el NOW() de Postgres con el que se llena verified_at.
            token_issued_at=result.issued_at.astimezone(ZoneInfo(APP_TIMEZONE)).replace(tzinfo=None),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
