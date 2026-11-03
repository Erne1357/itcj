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


def _photo_data_uri(photo) -> str | None:
    """Foto incrustada; no existe endpoint público de foto. Sin archivo = sin foto, nunca 500."""
    from itcj2.apps.credencial.services.photo_service import PHOTO_MIME, PhotoService

    try:
        data = PhotoService.read_bytes(photo)
    except Exception as e:
        logger.warning("credencial: foto ilegible user_id=%s (%s)", photo.user_id, type(e).__name__)
        return None
    return f"data:{PHOTO_MIME};base64," + base64.b64encode(data).decode()


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
        from itcj2.apps.credencial.services.card_service import CardService, display_name, program_label

        if result.status not in ("valid", "inactive"):
            return {}
        view = {
            "name": display_name(result.student),
            "photo_uri": _photo_data_uri(result.photo),
        }
        if result.status == "valid":  # mismas etiquetas que la línea 2 de la tarjeta
            view["program"] = program_label(db, result.student.id)
            view["role"] = CardService.role_label(db, result.student.id)
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
