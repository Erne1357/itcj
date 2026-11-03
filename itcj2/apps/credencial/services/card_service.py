"""Datos impresos en la credencial: una sola fuente para la tarjeta, el hero y la verificación."""
import logging
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

RoleLabel = Literal["Estudiante", "Egresado"]


@dataclass(frozen=True)
class CardData:
    user_id: int
    display_name: str
    control_number: str
    program_label: str | None
    role_label: RoleLabel
    has_photo: bool
    photo_ref: str | None


def display_name(user) -> str:
    """Orden de la credencial: Nombre Apellido paterno Apellido materno.

    Un nombre capturado TODO EN MAYÚSCULAS se imprime en tipo título, como la física.
    """
    name = " ".join(p for p in (user.first_name, user.last_name, user.middle_name) if p)
    return name.title() if name.isupper() else name


def program_label(db: Session, user_id: int) -> str | None:
    """Carrera del alumno con la etiqueta de la tarjeta (sin « EAD»/« CAMPUS II»)."""
    from itcj2.apps.credencial.services.display import program_display_name
    from itcj2.core.models.program import Program
    from itcj2.core.models.student_profile import StudentProfile

    name = (
        db.query(Program.name)
        .join(StudentProfile, StudentProfile.program_id == Program.id)
        .filter(StudentProfile.user_id == user_id)
        .scalar()
    )
    return program_display_name(name)


class CardService:
    @staticmethod
    def role_label(db: Session, user_id: int) -> RoleLabel:
        from fastapi import HTTPException
        from itcj2.core.services.authz_cache import cached_roles

        try:
            roles = cached_roles(db, user_id, "titulatec")
        except HTTPException:  # titulatec ausente o inactiva (CI con base vacía)
            return "Estudiante"
        return "Egresado" if "graduate" in roles else "Estudiante"

    @staticmethod
    def build(db: Session, user_id: int) -> CardData | None:
        """None si no es alumno (misma regla del shell: tiene nº de control)."""
        from itcj2.apps.credencial.models import CredentialPhoto
        from itcj2.apps.credencial.services.photo_service import PhotoService
        from itcj2.core.models.user import User

        user = db.get(User, user_id)
        if user is None or user.control_number is None:
            return None
        photo = db.get(CredentialPhoto, user_id)
        try:
            # Fila sin archivo = sin foto: ni hueco roto ni QR que verifique sin cara.
            has_photo = photo is not None and PhotoService.path(photo).is_file()
        except Exception as e:  # ruta insegura o volumen caído: se trata como sin foto
            logger.warning("credencial: foto inaccesible user_id=%s (%s)", user_id, type(e).__name__)
            has_photo = False
        return CardData(
            user_id=user.id,
            display_name=display_name(user),
            control_number=user.control_number,
            program_label=program_label(db, user.id),
            role_label=CardService.role_label(db, user.id),
            has_photo=has_photo,
            photo_ref=photo.ref if has_photo else None,
        )
