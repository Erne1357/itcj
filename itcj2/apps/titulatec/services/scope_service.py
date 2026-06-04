"""Alcance por carrera de un usuario administrativo de TitulaTec.

officer_programs(db, user_id):
  - "ALL" si el usuario tiene titulatec.process.api.read.all (admin/titulaciones/jefe).
  - si no: set de program_id ligados (core_program_positions) a los puestos titulatec
    que ocupa (UserPosition activa). Vacío = no ve nada hasta que el jefe lo asigne.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

READ_ALL = "titulatec.process.api.read.all"


def _user_perms(db: Session, user_id: int) -> set[str]:
    from itcj2.core.services.authz_service import get_user_permissions_for_app
    return set(get_user_permissions_for_app(db, user_id, "titulatec"))


def _program_ids_for_user(db: Session, user_id: int) -> set[int]:
    from itcj2.core.models.position import UserPosition, ProgramPosition
    rows = (
        db.query(ProgramPosition.program_id)
        .join(UserPosition, UserPosition.position_id == ProgramPosition.position_id)
        .filter(UserPosition.user_id == user_id, UserPosition.is_active.is_(True))
        .distinct()
        .all()
    )
    return {r[0] for r in rows}


def officer_programs(db: Session, user_id: int):
    """Devuelve 'ALL' o un set[int] de program_id que el usuario puede ver."""
    if READ_ALL in _user_perms(db, user_id):
        return "ALL"
    return _program_ids_for_user(db, user_id)
