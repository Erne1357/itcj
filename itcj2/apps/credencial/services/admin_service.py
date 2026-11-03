"""Consultas del panel de Servicios Escolares: busqueda de alumnos y bitacora."""
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StudentRow:
    user_id: int
    control_number: str
    full_name: str
    program: str | None
    has_photo: bool
    is_active: bool


@dataclass(frozen=True)
class VerificationRow:
    when: object  # datetime naive en hora local (NOW() de Postgres)
    student_id: int
    student_name: str
    control_number: str | None
    verifier_name: str | None
    result: str


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _full_name(first, last, middle) -> str:
    return " ".join(p for p in (first, last, middle) if p)


class AdminService:
    @staticmethod
    def search(db: Session, q: str, page: int, per_page: int = 25, only_missing: bool = False):
        """Alumnos (con nº de control) por prefijo de control o por nombre; una sola consulta con joins.

        Cada palabra de `q` debe coincidir con el control (prefijo) o con algun nombre/apellido.
        """
        from sqlalchemy import or_

        from itcj2.apps.credencial.models import CredentialPhoto
        from itcj2.apps.titulatec.utils.paging import Page, paginate_query
        from itcj2.core.models.program import Program
        from itcj2.core.models.student_profile import StudentProfile
        from itcj2.core.models.user import User

        query = (
            db.query(User.id, User.control_number, User.first_name, User.last_name, User.middle_name,
                     User.is_active, Program.name, CredentialPhoto.user_id)
            .outerjoin(CredentialPhoto, CredentialPhoto.user_id == User.id)
            .outerjoin(StudentProfile, StudentProfile.user_id == User.id)
            .outerjoin(Program, Program.id == StudentProfile.program_id)
            .filter(User.control_number.isnot(None))
        )
        for word in (q or "").split():
            pat = _like_escape(word)
            query = query.filter(or_(
                User.control_number.ilike(f"{pat}%", escape="\\"),
                User.first_name.ilike(f"%{pat}%", escape="\\"),
                User.last_name.ilike(f"%{pat}%", escape="\\"),
                User.middle_name.ilike(f"%{pat}%", escape="\\"),
            ))
        if only_missing:
            query = query.filter(CredentialPhoto.user_id.is_(None))
        query = query.order_by(User.last_name, User.middle_name, User.first_name, User.id)

        from itcj2.apps.credencial.services.display import program_display_name

        raw: Page = paginate_query(query, page, per_page)
        items = [
            StudentRow(uid, cn, _full_name(first, last, mid), program_display_name(prog),
                       photo_uid is not None, bool(active))
            for uid, cn, first, last, mid, active, prog, photo_uid in raw.items
        ]
        return Page(items=items, total=raw.total, page=raw.page, per_page=raw.per_page)

    @staticmethod
    def verifications(db: Session, page: int, per_page: int = 50):
        from sqlalchemy.orm import aliased

        from itcj2.apps.credencial.models import CredentialVerification as V
        from itcj2.apps.titulatec.utils.paging import Page, paginate_query
        from itcj2.core.models.user import User

        verifier = aliased(User)
        query = (
            db.query(V.verified_at, V.student_id, User.first_name, User.last_name, User.middle_name,
                     User.control_number, verifier.first_name, verifier.last_name, verifier.username, V.result)
            .join(User, User.id == V.student_id)
            .outerjoin(verifier, verifier.id == V.verifier_id)
            .order_by(V.verified_at.desc(), V.id.desc())
        )
        raw: Page = paginate_query(query, page, per_page)
        items = [
            VerificationRow(when, sid, _full_name(f, l, m), cn,
                            (_full_name(vf, vl, None) or vu) if (vf or vl or vu) else None, res)
            for when, sid, f, l, m, cn, vf, vl, vu, res in raw.items
        ]
        return Page(items=items, total=raw.total, page=raw.page, per_page=raw.per_page)
