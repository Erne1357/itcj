# itcj/core/services/mobile_service.py
"""
Servicio para la logica del dashboard movil.
Maneja deteccion de tipo de usuario, listado de apps moviles y deteccion de dispositivo.
"""
from __future__ import annotations
from typing import Optional
from itcj.core.extensions import db
from itcj.core.models.app import App
from itcj.core.models.user import User
from itcj.core.services.authz_service import user_roles_in_app, has_any_assignment


def is_student(user_id: int) -> bool:
    """Determina si el usuario es estudiante basandose en control_number."""
    user = db.session.query(User).get(user_id)
    return user is not None and user.control_number is not None


def get_user_type(user_id: int) -> str:
    """Retorna 'student' o 'staff'."""
    return "student" if is_student(user_id) else "staff"


def get_user_for_mobile(user_id: int) -> Optional[User]:
    """Obtiene el objeto User para el dashboard movil."""
    return db.session.query(User).get(user_id)


def get_mobile_apps_for_user(user_id: int) -> list[dict]:
    """
    Retorna lista de apps habilitadas para movil que el usuario puede acceder.
    - Estudiantes: solo apps con visible_to_students=True
    - Staff: todas las apps segun sus permisos
    """
    user_type = get_user_type(user_id)

    query = App.query.filter_by(is_active=True, mobile_enabled=True)

    if user_type == "student":
        query = query.filter_by(visible_to_students=True)

    apps = query.order_by(App.name.asc()).all()

    result = []
    for app in apps:
        # Verificar que el usuario tenga alguna asignacion en la app
        if has_any_assignment(user_id, app.key, include_positions=True):
            app_data = app.to_dict(include_mobile=True)
            roles = user_roles_in_app(user_id, app.key)
            app_data["user_roles"] = sorted(list(roles))
            result.append(app_data)

    return result


def is_mobile_user_agent(user_agent_string: str) -> bool:
    """Deteccion basica de dispositivo movil via User-Agent."""
    if not user_agent_string:
        return False
    ua = user_agent_string.lower()
    mobile_keywords = [
        'mobile', 'android', 'iphone', 'ipad', 'ipod',
        'windows phone', 'opera mini', 'opera mobi',
        'webos', 'blackberry',
    ]
    return any(kw in ua for kw in mobile_keywords)
