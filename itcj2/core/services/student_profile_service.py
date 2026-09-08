"""Perfil de alumno: fila PEREZOSA de `core_student_profile` (§3.1 del spec).

Ninguno de los tres métodos hace commit. Los tres consumidores (T20 `_convert`,
T21 `confirm_contact`, T22 `approve`) escriben dentro de su propia transacción y
commitean ellos; un commit aquí partiría esa transacción a la mitad.
"""
from sqlalchemy.orm import Session

from itcj2.core.models.student_profile import StudentProfile


class StudentProfileService:

    @staticmethod
    def get_or_create(db: Session, user_id: int) -> StudentProfile:
        """Devuelve el perfil, creándolo si no existe. NO hace commit.

        Hace `flush()` tras el `add()` para que `set_fields` y el `commit()` del
        llamador vean la fila.
        """
        row = db.get(StudentProfile, user_id)
        if row is None:
            row = StudentProfile(user_id=user_id)
            db.add(row)
            db.flush()
        return row

    @staticmethod
    def set_fields(db: Session, user_id: int, **fields) -> StudentProfile:
        """Upsert de columnas del perfil. NO hace commit.

        Nunca toca `core_users.email` (D12): el correo personal vive aquí.
        """
        row = StudentProfileService.get_or_create(db, user_id)
        for k, v in fields.items():
            setattr(row, k, v)
        db.flush()
        return row

    @staticmethod
    def mark_contact_verified(db: Session, user_id: int) -> StudentProfile:
        """Sella `contact_email_verified_at`. NO hace commit."""
        from datetime import datetime

        row = StudentProfileService.get_or_create(db, user_id)
        row.contact_email_verified_at = datetime.now()
        db.flush()
        return row
