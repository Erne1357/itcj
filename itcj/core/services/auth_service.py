from itcj.apps.agendatec.models import db
from itcj.core.models.user import User
from itcj.core.models.role import Role
from itcj.core.utils.security import verify_nip
from flask import current_app
from datetime import datetime
from zoneinfo import ZoneInfo

def authenticate(control_number: str, nip: str):
    """
    Retorna dict con {id, role, control_number, full_name} si ok, o None si falla.
    Solo autenticamos estudiantes por ahora (tienen control_number).
    """
    # Busca usuario activo por control_number
    user: User | None = (
        db.session.query(User)
        .filter(User.control_number == control_number, User.is_active == True)  # noqa: E712
        .first()
    )
    if not user or not user.password_hash:
        return None

    # Verifica NIP
    if not verify_nip(nip, user.password_hash):
        return None

    # Actualiza last_login
    user.last_login = datetime.now()
    db.session.commit()

    role_name = user.role.name if user.role else None

    return {
        "id": user.id,
        "role": role_name,
        "control_number": user.control_number,
        "full_name": user.full_name,
        "email": user.email,
    }

def authenticate_by_username(username: str, nip: str):
    u = db.session.query(User).filter_by(username=username, is_active=True).first()


    if not u:
        return None
    if not verify_nip(nip, u.password_hash):
        return None
    
    # Actualiza last_login
    u.last_login = datetime.now(ZoneInfo("America/Monterrey"))
    db.session.commit()
    
    role = db.session.query(Role).get(u.role_id)
    return {
        "id": u.id,
        "role": role.name if role else None,
        "control_number": u.control_number,
        "full_name": u.full_name,
        "email": u.email,
        "username": u.username,
    }