def role_home(roles) -> str:
    """
    Determina la ruta home basada en el rol de mayor prioridad del usuario.

    Args:
        roles: Puede ser un string (rol único) o un set/list de strings (múltiples roles)

    Returns:
        str: URL de la página home correspondiente al rol de mayor prioridad
    """
    ROLE_PRIORITY = [
        "admin",
        "staff",
        "coordinator",
        "social_service",
        "student",
        "graduate",
    ]

    ROLE_ROUTES = {
        "admin": "/itcj/dashboard",
        "staff": "/itcj/dashboard",
        "coordinator": "/itcj/dashboard",
        "social_service": "/itcj/dashboard",
        "student": "/itcj/m/",
        # Egresado de TitulaTec (2026-09-15): `import_rows` le da este rol en la
        # app `itcj`. Mismo shell móvil que el alumno, sin pasar por el rebote de
        # `/itcj/dashboard` a quien no tiene rol de escritorio.
        "graduate": "/itcj/m/",
    }

    if isinstance(roles, str):
        user_roles = {roles}
    else:
        user_roles = set(roles)

    if not user_roles:
        return "/"

    for role in ROLE_PRIORITY:
        if role in user_roles:
            return ROLE_ROUTES.get(role, "/")

    if user_roles == {"student"}:
        return "/itcj/m/"

    return "/itcj/dashboard"
