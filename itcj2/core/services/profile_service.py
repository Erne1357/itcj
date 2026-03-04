from sqlalchemy import desc
from sqlalchemy.orm import Session

from itcj2.core.models.user import User
from itcj2.core.models.position import UserPosition
from itcj2.core.models.app import App
from itcj2.core.services.authz_service import (
    user_roles_in_app,
    user_direct_perms_in_app,
    effective_perms,
)


def get_user_profile_data(db: Session, user_id: int) -> dict:
    """
    Obtiene todos los datos necesarios para el perfil del usuario
    """
    user = db.get(User, user_id)
    if not user:
        return None

    # 1. Información básica
    profile = {
        'id': user.id,
        'full_name': user.full_name,
        'email': user.email,
        'username': user.username,
        'control_number': user.control_number,
        'roles': user_roles_in_app(db, user_id, 'itcj'),
        'is_active': user.is_active,
        'created_at': user.created_at,
        'last_login_at': user.last_login
    }

    # 2. Puestos organizacionales activos
    active_positions = db.query(UserPosition).filter_by(
        user_id=user_id,
        is_active=True
    ).all()

    profile['positions'] = [
        {
            'id': p.position_id,
            'title': p.position.title,
            'code': p.position.code,
            'department': {
                'id': p.position.department.id,
                'name': p.position.department.name,
                'code': p.position.department.code,
                'icon_class': p.position.department.icon_class
            } if p.position.department else None,
            'start_date': p.start_date,
            'notes': p.notes
        }
        for p in active_positions
    ]

    # 3. Roles y permisos por aplicación
    apps = db.query(App).filter_by(is_active=True).all()
    profile['app_assignments'] = {}

    for app in apps:
        roles = user_roles_in_app(db, user_id, app.key)
        direct_perms = user_direct_perms_in_app(db, user_id, app.key)
        perms_data = effective_perms(db, user_id, app.key)

        profile['app_assignments'][app.key] = {
            'app_name': app.name,
            'app_icon': app.icon_class if hasattr(app, 'icon_class') else 'bi-app',
            'roles': list(roles) if isinstance(roles, set) else roles,
            'direct_permissions': list(direct_perms) if isinstance(direct_perms, set) else direct_perms,
            'effective_permissions': perms_data['effective'],
            'roles_via_positions': perms_data.get('roles_via_positions', []),
            'perms_via_positions_direct': perms_data.get('perms_via_positions_direct', []),
            'perms_via_position_roles': perms_data.get('perms_via_position_roles', [])
        }

    return profile


def get_user_activity(db: Session, user_id: int, limit: int = 10) -> list:
    """
    Obtiene la actividad reciente del usuario.
    TODO: Implementar cuando se tenga un sistema de auditoría/logs
    """
    return []


def get_user_notifications(db: Session, user_id: int, unread_only: bool = False, limit: int = 20) -> dict:
    """
    Obtiene las notificaciones del usuario
    """
    from itcj2.core.models.notification import Notification

    query = db.query(Notification).filter_by(user_id=user_id)

    if unread_only:
        query = query.filter_by(is_read=False)

    notifications = query.order_by(desc(Notification.created_at)).limit(limit).all()

    return {
        'notifications': [
            {
                'id': n.id,
                'title': n.title,
                'body': n.body,
                'app_name': n.app_name,
                'type': n.type,
                'is_read': n.is_read,
                'created_at': n.created_at,
                'data': n.data,
            }
            for n in notifications
        ],
        'unread_count': db.query(Notification).filter_by(
            user_id=user_id,
            is_read=False
        ).count()
    }
