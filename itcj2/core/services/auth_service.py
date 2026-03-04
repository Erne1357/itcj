from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from itcj2.core.models.role import Role
from itcj2.core.models.user import User
from itcj2.core.utils.security import verify_nip


def authenticate(db: Session, control_number: str, nip: str):
    """
    Retorna dict con {id, role, control_number, full_name, email} si ok, o None si falla.
    """
    user: User | None = (
        db.query(User)
        .filter(User.control_number == control_number, User.is_active == True)  # noqa: E712
        .first()
    )
    if not user or not user.password_hash:
        return None

    if not verify_nip(nip, user.password_hash):
        return None

    user.last_login = datetime.now()
    db.commit()

    return {
        "id": user.id,
        "role": user.role.name if user.role else None,
        "control_number": user.control_number,
        "full_name": user.full_name,
        "email": user.email,
    }


def authenticate_by_username(db: Session, username: str, nip: str):
    u = db.query(User).filter_by(username=username, is_active=True).first()
    if not u:
        return None
    if not verify_nip(nip, u.password_hash):
        return None

    u.last_login = datetime.now(ZoneInfo("America/Monterrey"))
    db.commit()

    role = db.get(Role, u.role_id) if u.role_id else None
    return {
        "id": u.id,
        "role": role.name if role else None,
        "control_number": u.control_number,
        "full_name": u.full_name,
        "email": u.email,
        "username": u.username,
    }
