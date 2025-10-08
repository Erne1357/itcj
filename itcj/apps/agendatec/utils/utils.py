from itcj.core.services.authz_service import user_roles_in_app, get_user_permissions_for_app

def get_role_agenda(user_id):
    """Obtiene el rol del usuario en AgendaTec."""
    user_roles = user_roles_in_app(user_id, "agendatec")
    user_roles = list(user_roles)
    return user_roles[0] if user_roles else None

def get_permissions_agenda(user_id):
    """Obtiene los permisos del usuario en AgendaTec."""
    return get_user_permissions_for_app(user_id, "agendatec")
