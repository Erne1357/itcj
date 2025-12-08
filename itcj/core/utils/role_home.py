def role_home(roles) -> str:
    """
    Determina la ruta home basada en el rol de mayor prioridad del usuario.
    
    Args:
        roles: Puede ser un string (rol único) o un set/list de strings (múltiples roles)
    
    Returns:
        str: URL de la página home correspondiente al rol de mayor prioridad
    """
    
    # Jerarquía de roles ordenada por prioridad (mayor a menor)
    ROLE_PRIORITY = [
        "admin",           # Máxima prioridad
        "staff", 
        "coordinator",
        "social_service",
        "student"          # Menor prioridad
    ]
    
    # Mapeo de roles a rutas home
    ROLE_ROUTES = {
        "admin": "/itcj/dashboard",
        "staff": "/itcj/dashboard", 
        "coordinator": "/itcj/dashboard",
        "social_service": "/itcj/dashboard",
        "student": "/agendatec/student/home"
    }
    
    # Convertir a set si es string individual
    if isinstance(roles, str):
        user_roles = {roles}
    else:
        user_roles = set(roles)
    
    # Si no tiene roles, ir a home general
    if not user_roles:
        return "/"
    
    # Buscar el rol de mayor prioridad que tenga el usuario
    for role in ROLE_PRIORITY:
        if role in user_roles:
            return ROLE_ROUTES.get(role, "/")
    
    # Si solo tiene rol de student, ir a AgendaTec
    if user_roles == {"student"}:
        return "/agendatec/student/home"
    
    # Si tiene otros roles no reconocidos o combinación con student, ir a dashboard ITCJ
    return "/itcj/dashboard"