"""
Utilidades para determinar el nivel de acceso al inventario.

Unifica la lógica de roles, posiciones organizacionales y permisos directos
para evitar que usuarios con permisos válidos sean bloqueados por checks
manuales de roles.
"""
from __future__ import annotations
from itcj.core.services.authz_service import (
    user_roles_in_app,
    _get_users_with_position,
    get_user_permissions_for_app,
)

# Roles que otorgan acceso completo al inventario
_FULL_ACCESS_ROLES = {'admin', 'tech_desarrollo', 'tech_soporte'}

# Posiciones que otorgan acceso completo
_FULL_ACCESS_POSITIONS = ['secretary_comp_center']

# Permisos que implican acceso completo (lectura global)
_FULL_ACCESS_PERMS = {
    'helpdesk.inventory.api.read.all',
    'helpdesk.inventory_groups.api.read.all',
}

# Permisos que implican acceso a nivel departamento
_DEPT_ACCESS_PERMS = {
    'helpdesk.inventory.api.read.own_dept',
    'helpdesk.inventory_groups.api.read.own_dept',
}


def has_full_inventory_access(user_id: int, user_roles: set[str] | None = None) -> bool:
    """
    Determina si el usuario tiene acceso COMPLETO al inventario (todos los departamentos).

    Retorna True si cumple CUALQUIERA de:
      1. Tiene un rol privilegiado (admin, tech_desarrollo, tech_soporte)
      2. Tiene la posición de secretaría del Centro de Cómputo
      3. Tiene permisos efectivos de lectura global del inventario
    """
    if user_roles is None:
        user_roles = user_roles_in_app(user_id, 'helpdesk')

    # 1. Roles privilegiados
    if _FULL_ACCESS_ROLES & user_roles:
        return True

    # 2. Posición de secretaría del CC
    if user_id in _get_users_with_position(_FULL_ACCESS_POSITIONS):
        return True

    # 3. Permisos efectivos de lectura global
    user_perms = get_user_permissions_for_app(user_id, 'helpdesk')
    if _FULL_ACCESS_PERMS & user_perms:
        return True

    return False


def has_dept_inventory_access(user_id: int, user_roles: set[str] | None = None) -> bool:
    """
    Determina si el usuario tiene acceso a nivel DEPARTAMENTAL al inventario.

    Retorna True si cumple CUALQUIERA de:
      1. Es jefe de departamento
      2. Tiene permisos efectivos de lectura departamental
    """
    if user_roles is None:
        user_roles = user_roles_in_app(user_id, 'helpdesk')

    if 'department_head' in user_roles:
        return True

    user_perms = get_user_permissions_for_app(user_id, 'helpdesk')
    if _DEPT_ACCESS_PERMS & user_perms:
        return True

    return False
