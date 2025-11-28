# Este servicio centralizará toda la lógica de obtención de datos del perfil
from itcj.core.models.user import User
from itcj.core.models.position import UserPosition
from itcj.core.services.authz_service import (
    user_roles_in_app, 
    user_direct_perms_in_app,  # Cambiado
    effective_perms            # Cambiado
)
from itcj.core.models.app import App
from sqlalchemy import desc

def get_user_profile_data(user_id: int) -> dict:
    """
    Obtiene todos los datos necesarios para el perfil del usuario
    """
    user = User.query.get(user_id)
    if not user:
        return None
    
    # 1. Información básica
    profile = {
        'id': user.id,
        'full_name': user.full_name,
        'email': user.email,
        'username': user.username,
        'control_number': user.control_number,
        'roles': user_roles_in_app(user_id, 'itcj'),
        'is_active': user.is_active,
        'created_at': user.created_at,
        'last_login': user.last_login if hasattr(user, 'last_login') else None
    }
    
    # 2. Puestos organizacionales activos
    active_positions = UserPosition.query.filter_by(
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
    apps = App.query.filter_by(is_active=True).all()
    profile['app_assignments'] = {}
    
    for app in apps:
        # Usar las funciones correctas
        roles = user_roles_in_app(user_id, app.key)
        direct_perms = user_direct_perms_in_app(user_id, app.key)  # Corregido
        perms_data = effective_perms(user_id, app.key)             # Corregido
        
        profile['app_assignments'][app.key] = {
            'app_name': app.name,
            'app_icon': app.icon_class if hasattr(app, 'icon_class') else 'bi-app',
            'roles': list(roles) if isinstance(roles, set) else roles,
            'direct_permissions': list(direct_perms) if isinstance(direct_perms, set) else direct_perms,
            'effective_permissions': perms_data['effective'],  # Usar el dict devuelto
            'roles_via_positions': perms_data.get('roles_via_positions', []),
            'perms_via_positions_direct': perms_data.get('perms_via_positions_direct', []),
            'perms_via_position_roles': perms_data.get('perms_via_position_roles', [])
        }
    
    return profile

def get_user_activity(user_id: int, limit: int = 10) -> list:
    """
    Obtiene la actividad reciente del usuario
    TODO: Implementar cuando tengas un sistema de auditoría/logs
    """
    # Por ahora retorna una lista vacía
    # En el futuro, esto consultaría una tabla de audit_logs
    return []

def get_user_notifications(user_id: int, unread_only: bool = False, limit: int = 20) -> dict:
    """
    Obtiene las notificaciones del usuario
    """
    from itcj.core.models.notification import Notification
    
    query = Notification.query.filter_by(user_id=user_id)
    
    if unread_only:
        query = query.filter_by(is_read=False)
    
    notifications = query.order_by(desc(Notification.created_at)).limit(limit).all()
    
    return {
        'notifications': [
            {
                'id': n.id,
                'title': n.title,
                'message': n.message,
                'app_name': n.app_name,
                'notification_type': n.notification_type,
                'is_read': n.is_read,
                'created_at': n.created_at,
                'action_url': n.action_url
            }
            for n in notifications
        ],
        'unread_count': Notification.query.filter_by(
            user_id=user_id,
            is_read=False
        ).count()
    }