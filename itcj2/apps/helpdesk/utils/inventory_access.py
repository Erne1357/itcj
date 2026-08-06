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


# Permiso de scope por sub-departamento (jerárquico, por procedencia)
_INVENTORY_SUBTREE_PERM = "helpdesk.inventory.api.read.subtree"


def visible_department_ids(
    db,
    user: dict,
    *,
    extra_subtree_perms: set[str] | None = None,
) -> set[int] | None:
    """Departamentos de inventario visibles para el usuario.

    Retorna ``None`` si ve TODO (acceso completo / admin global). En otro caso, el
    set de department_ids visibles = (su departamento, si tiene acceso departamental)
    ∪ (subárbol jerárquico por procedencia, por cada permiso ``.subtree`` consultado).

    ``extra_subtree_perms`` añade anclas a la de items (``.inventory.api.read.subtree``),
    para los módulos que tienen su propio permiso: grupos, campañas, bajas,
    estadísticas, exportación. Cada módulo pasa el suyo, porque la resolución es por
    PROCEDENCIA: un permiso aporta el subárbol de LOS PUESTOS QUE LO OTORGAN, no una
    unión global de todos los puestos del usuario. Consultar el ancla equivocada deja
    el scope vacío aunque el guard haya pasado.

    ADITIVO/no-breaking: sin ``.subtree`` el resultado es el mismo depto de siempre.
    Un set vacío ⇒ no ve nada (fail-closed; el caller filtra por ``id IN {-1}``).
    """
    from itcj2.dependencies import is_global_admin
    from itcj2.core.services.departments_service import app_departments
    from itcj2.core.services.scope_service import subtree_scope_for

    uid = int(user["sub"])

    if is_global_admin(user) or has_full_inventory_access(db, uid) or is_comp_center_user(db, uid):
        return None

    ids: set[int] = set()
    # Acceso departamental "clásico" (.own_dept / department_head) → TODOS los
    # departamentos que le dan acceso a helpdesk, no uno solo: con multi-puesto el
    # resolver agnóstico podía elegir un departamento ajeno a la app, y a quien
    # tiene dos departamentos con acceso le mostraba solo uno.
    if has_dept_inventory_access(db, uid):
        ids |= {d.id for d in app_departments(db, uid, "helpdesk")}
    # Scope jerárquico: subárbol de los puestos que otorgan cada permiso .subtree.
    for perm_code in {_INVENTORY_SUBTREE_PERM} | (extra_subtree_perms or set()):
        ids |= subtree_scope_for(db, uid, "helpdesk", perm_code)
    return ids
