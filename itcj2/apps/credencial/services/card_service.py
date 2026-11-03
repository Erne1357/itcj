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

    # Texto y paso de letra de las líneas impresas (los usa _card.html).
    @property
    def line2(self) -> str:
        return f"{self.program_label} / {self.role_label}" if self.program_label else self.role_label

    @property
    def fit1(self) -> str:
        from itcj2.apps.credencial.services.display import fit_class
        return fit_class(f"{self.display_name} / {self.control_number}")

    @property
    def fit2(self) -> str:
        from itcj2.apps.credencial.services.display import fit_class
        return fit_class(self.line2)


def _as_printed(name: str) -> str:
    """Un nombre capturado TODO EN MAYÚSCULAS se imprime en tipo título, como la física."""
    return name.title() if name.isupper() else name


def display_name_parts(first: str | None, last: str | None, middle: str | None) -> str:
    """Orden de la credencial: Nombre Apellido paterno Apellido materno (también lo usa el panel)."""
    return _as_printed(" ".join(p for p in (first, last, middle) if p))


def display_name(user) -> str:
    return display_name_parts(user.first_name, user.last_name, user.middle_name)


def short_name(user) -> str:
    """Primer nombre y apellido paterno (reverso de la tarjeta)."""
    first = (user.first_name or "").split()[:1]
    return _as_printed(" ".join(first + ([user.last_name] if user.last_name else [])))


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
        has_photo = PhotoService.has_file(photo)  # sin archivo: ni hueco roto ni QR sin cara
        return CardData(
            user_id=user.id,
            display_name=display_name(user),
            control_number=user.control_number,
            program_label=program_label(db, user.id),
            role_label=CardService.role_label(db, user.id),
            has_photo=has_photo,
            photo_ref=photo.ref if has_photo else None,
        )
