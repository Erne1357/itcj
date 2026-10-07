"""
Servicio para la lógica del dashboard móvil.
"""
from __future__ import annotations
from typing import Optional

from sqlalchemy.orm import Session

from itcj2.core.models.app import App
from itcj2.core.models.user import User


def is_student(db: Session, user_id: int) -> bool:
    user = db.get(User, user_id)
    return user is not None and user.control_number is not None


def get_user_type(db: Session, user_id: int) -> str:
    return "student" if is_student(db, user_id) else "staff"


def get_user_for_mobile(db: Session, user_id: int) -> Optional[User]:
    return db.get(User, user_id)


def get_mobile_apps_for_user(db: Session, user_id: int) -> list[dict]:
    """
    Retorna lista de apps habilitadas para móvil que el usuario puede acceder.
    - Estudiantes: solo apps con visible_to_students=True
    - Staff: todas las apps según sus permisos
    """
    # Del caché de authz (los MISMOS valores e invalidación que el control de
    # acceso): perf 2026-10-07, antes eran ~6 consultas por app en cada carga
    # del shell móvil.
    from itcj2.core.services.authz_cache import cached_has_assignment, cached_roles

    user_type = get_user_type(db, user_id)

    query = db.query(App).filter_by(is_active=True, mobile_enabled=True)
    if user_type == "student":
        query = query.filter_by(visible_to_students=True)

    apps = query.order_by(App.name.asc()).all()
    apps = [app for app in apps if app.key != 'itcj']

    result = []
    for app in apps:
        if cached_has_assignment(db, user_id, app.key):
            app_data = app.to_dict(include_mobile=True)
            roles = cached_roles(db, user_id, app.key)
            app_data["user_roles"] = sorted(list(roles))
            result.append(app_data)

    return result


def is_mobile_user_agent(user_agent_string: str) -> bool:
    if not user_agent_string:
        return False
    ua = user_agent_string.lower()
    mobile_keywords = [
        'mobile', 'android', 'iphone', 'ipad', 'ipod',
        'windows phone', 'opera mini', 'opera mobi',
        'webos', 'blackberry',
    ]
    return any(kw in ua for kw in mobile_keywords)
