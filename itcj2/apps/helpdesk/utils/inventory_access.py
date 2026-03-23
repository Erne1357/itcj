"""
Utilidades para determinar el nivel de acceso al inventario.

Unifica la lógica de roles, posiciones organizacionales y permisos directos
para evitar que usuarios con permisos válidos sean bloqueados por checks
manuales de roles.

Equivalente de itcj/apps/helpdesk/utils/inventory_access.py adaptado a itcj2
(SQLAlchemy 2.0 con sesión explícita).
"""
from __future__ import annotations

# Roles que otorgan acceso completo al inventario
_FULL_ACCESS_ROLES = {"admin", "tech_desarrollo", "tech_soporte"}

# Permisos que implican acceso completo (lectura global)
_FULL_ACCESS_PERMS = {
    "helpdesk.inventory.api.read.all",
    "helpdesk.inventory_groups.api.read.all",
}

# Permisos que implican acceso a nivel departamento
_DEPT_ACCESS_PERMS = {
    "helpdesk.inventory.api.read.own_dept",
    "helpdesk.inventory_groups.api.read.own_dept",
}

# Posiciones que otorgan acceso completo
_FULL_ACCESS_POSITIONS = ["secretary_comp_center"]


def has_full_inventory_access(
    db,
    user_id: int,
    user_roles: set[str] | None = None,
) -> bool:
    """
    Determina si el usuario tiene acceso COMPLETO al inventario (todos los departamentos).

    Retorna True si cumple CUALQUIERA de:
      1. Tiene un rol privilegiado (admin, tech_desarrollo, tech_soporte)
      2. Tiene la posición de secretaría del Centro de Cómputo
      3. Tiene permisos efectivos de lectura global del inventario
    """
    from itcj2.core.services.authz_service import user_roles_in_app, get_user_permissions_for_app

    if user_roles is None:
        user_roles = user_roles_in_app(db, user_id, "helpdesk")

    # 1. Roles privilegiados
    if _FULL_ACCESS_ROLES & user_roles:
        return True

    # 2. Posición de secretaría del CC
    try:
        from itcj2.core.services.authz_service import _get_users_with_position
        if user_id in _get_users_with_position(db, _FULL_ACCESS_POSITIONS):
            return True
    except (ImportError, TypeError):
        # Si la función no acepta db session, intentamos sin ella
        pass

    # 3. Permisos efectivos de lectura global
    user_perms = get_user_permissions_for_app(db, user_id, "helpdesk")
    if _FULL_ACCESS_PERMS & user_perms:
        return True

    return False


def is_comp_center_user(db, user_id: int) -> bool:
    """
    Determina si el usuario pertenece actualmente al Centro de Cómputo.

    Equivalente al check is_comp_center en pages/inventory.py:
      dept.code == 'comp_center' or dept.name == 'CENTRO DE COMPUTO'
    """
    from itcj2.core.models.user import User
    user = db.get(User, user_id)
    if not user:
        return False
    dept = user.get_current_department()
    return bool(dept and (dept.code == "comp_center" or dept.name == "CENTRO DE COMPUTO"))


def has_dept_inventory_access(
    db,
    user_id: int,
    user_roles: set[str] | None = None,
) -> bool:
    """
    Determina si el usuario tiene acceso a nivel DEPARTAMENTAL al inventario.

    Retorna True si cumple CUALQUIERA de:
      1. Es jefe de departamento
      2. Tiene permisos efectivos de lectura departamental
    """
    from itcj2.core.services.authz_service import user_roles_in_app, get_user_permissions_for_app

    if user_roles is None:
        user_roles = user_roles_in_app(db, user_id, "helpdesk")

    if "department_head" in user_roles:
        return True

    user_perms = get_user_permissions_for_app(db, user_id, "helpdesk")
    if _DEPT_ACCESS_PERMS & user_perms:
        return True

    return False
