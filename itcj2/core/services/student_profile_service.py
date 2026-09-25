"""Perfil de alumno: fila PEREZOSA de `core_student_profile` (§3.1 del spec).

Ninguno de los tres métodos hace commit: el llamador escribe dentro de su propia
transacción y commitea él; un commit aquí la partiría a la mitad. Hoy el único
consumidor externo que escribe es `EnrollmentRequestService._create_account()`
(`set_fields` justo después de crear el `User` nuevo, cuando Centro de Cómputo
da el acceso con `grant_access`, o al aprobar en el modo alterno), más el
prellenado de la encuesta de egresados (`pages/public.py`, solo `get_or_create`). `_convert()`
—la rama CON cuenta— no toca este service a propósito (su propio docstring lo
llama invariante 1): una cuenta que ya existía no debe heredar el perfil de una
solicitud que pudo llenar cualquiera.
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

        CAMBIAR `contact_email` LIMPIA `contact_email_verified_at`. El sello
        habla de UNA dirección concreta, no del perfil: sin esto sobrevivía al
        correo que certificaba, y la bandeja de solicitudes pintaba en verde una
        dirección nueva que nadie confirmó jamás —basta con que la persona haya
        verificado otra en una convocatoria anterior—. Reescribir el MISMO
        correo NO lo limpia (se compara antes/después, sin distinguir
        mayúsculas): cualquier llamador que vuelva a guardar la misma dirección
        no debe tirar una verificación ya hecha. Hoy el único llamador
        (`EnrollmentRequestService._create_account`, al dar el acceso a una
        cuenta nueva) escribe una sola vez, al crear el perfil, así que este caso no se ejerce en producción
        — la guarda queda lista para cuando exista una segunda escritura.
        """
        row = StudentProfileService.get_or_create(db, user_id)
        if "contact_email" in fields:
            antes = (row.contact_email or "").strip().lower()
            ahora = (fields["contact_email"] or "").strip().lower()
            if antes != ahora:
                row.contact_email_verified_at = None
        for k, v in fields.items():
            setattr(row, k, v)
        db.flush()
        return row

    @staticmethod
    def mark_contact_verified(db: Session, user_id: int) -> StudentProfile:
        """Sella `contact_email_verified_at`. NO hace commit.

        Sin llamadores hoy: la liga que lo invocaba (`confirm_contact`, de
        `EnrollmentRequestService`) se retiró el 2026-09-15 junto con su ruta
        (`GET /titulatec/inscripcion/correo`) y su plantilla. Se conserva
        porque `contact_email_verified_at` sigue siendo una columna real de
        `core_student_profile` que un futuro flujo de verificación de correo
        puede necesitar sellar.
        """
        from datetime import datetime

        row = StudentProfileService.get_or_create(db, user_id)
        row.contact_email_verified_at = datetime.now()
        db.flush()
        return row
