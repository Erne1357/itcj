"""
Utilidades generales de AgendaTec.
Fuente: itcj/apps/prorrogas_tec/utils/utils.py
"""
from itcj2.database import SessionLocal


def get_role_prorroga(user_id: int):
    """Obtiene el rol del usuario en AgendaTec."""
    from itcj2.core.services.authz_service import user_roles_in_app

    db = SessionLocal()
    try:
        roles = list(user_roles_in_app(db, user_id, "prorrogas_tec"))
        return roles[0] if roles else None
    finally:
        db.close()


def get_permissions_prorroga(user_id: int):
    """Obtiene los permisos del usuario en AgendaTec."""
    from itcj2.core.services.authz_service import get_user_permissions_for_app

    db = SessionLocal()
    try:
        return get_user_permissions_for_app(db, user_id, "prorrogas_tec")
    finally:
        db.close()
