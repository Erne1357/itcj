# itcj/core/services/authz_service.py
from __future__ import annotations
from typing import Iterable, Optional, Tuple, Set, Dict
from sqlalchemy.exc import IntegrityError
from itcj.core.extensions import db
from itcj.core.models.app import App
from itcj.core.models.role import Role
from itcj.core.models.permission import Permission
from itcj.core.models.role_permission import RolePermission
from itcj.core.models.user_app_role import UserAppRole
from itcj.core.models.user_app_perm import UserAppPerm

# ---------------------------
# Lookups básicos
# ---------------------------

def get_app_by_key(app_key: str) -> Optional[App]:
    return db.session.query(App).filter_by(key=app_key, is_active=True).first()

def get_or_404_app(app_key: str) -> App:
    app = get_app_by_key(app_key)
    if not app:
        from flask import abort
        abort(404, description=f"App '{app_key}' no existe o está inactiva.")
    return app

def get_role_by_name(role_name: str) -> Optional[Role]:
    return db.session.query(Role).filter_by(name=role_name).first()

def get_perm(app_id: int, code: str) -> Optional[Permission]:
    return db.session.query(Permission).filter_by(app_id=app_id, code=code).first()

# ---------------------------
# CRUD de asignaciones
# ---------------------------

def grant_role(user_id: int, app_key: str, role_name: str) -> bool:
    """Asigna un rol de app al usuario. True si creó, False si ya existía."""
    app = get_or_404_app(app_key)
    role = get_role_by_name(role_name)
    if not role:
        from flask import abort
        abort(400, description=f"Rol '{role_name}' no existe.")

    exists = db.session.query(UserAppRole).filter_by(
        user_id=user_id, app_id=app.id, role_id=role.id
    ).first()
    if exists:
        return False

    db.session.add(UserAppRole(user_id=user_id, app_id=app.id, role_id=role.id))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return False
    return True

def revoke_role(user_id: int, app_key: str, role_name: str) -> bool:
    app = get_or_404_app(app_key)
    role = get_role_by_name(role_name)
    if not role:
        return False
    q = db.session.query(UserAppRole).filter_by(
        user_id=user_id, app_id=app.id, role_id=role.id
    )
    if q.count() == 0:
        return False
    q.delete()
    db.session.commit()
    return True

def grant_perm(user_id: int, app_key: str, perm_code: str, *, allow: bool = True) -> bool:
    """Asigna permiso directo a usuario en app (allow=True/False)."""
    app = get_or_404_app(app_key)
    perm = get_perm(app.id, perm_code)
    if not perm:
        from flask import abort
        abort(400, description=f"Permiso '{perm_code}' no existe en app '{app_key}'.")

    exists = db.session.query(UserAppPerm).filter_by(
        user_id=user_id, app_id=app.id, perm_id=perm.id
    ).first()
    if exists:
        # Actualiza allow si difiere
        changed = (exists.allow != allow)
        exists.allow = allow
        if changed:
            db.session.commit()
        return changed

    db.session.add(UserAppPerm(user_id=user_id, app_id=app.id, perm_id=perm.id, allow=allow))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return False
    return True

def revoke_perm(user_id: int, app_key: str, perm_code: str) -> bool:
    app = get_or_404_app(app_key)
    perm = get_perm(app.id, perm_code)
    if not perm:
        return False
    q = db.session.query(UserAppPerm).filter_by(
        user_id=user_id, app_id=app.id, perm_id=perm.id
    )
    if q.count() == 0:
        return False
    q.delete()
    db.session.commit()
    return True

# ---------------------------
# Lecturas / agregados
# ---------------------------

def user_roles_in_app(user_id: int, app_key: str) -> Set[str]:
    app = get_or_404_app(app_key)
    rows = (
        db.session.query(Role.name)
        .join(UserAppRole, UserAppRole.role_id == Role.id)
        .filter(UserAppRole.user_id == user_id, UserAppRole.app_id == app.id)
        .all()
    )
    return {r[0] for r in rows}

def user_direct_perms_in_app(user_id: int, app_key: str) -> Set[str]:
    app = get_or_404_app(app_key)
    rows = (
        db.session.query(Permission.code)
        .join(UserAppPerm, UserAppPerm.perm_id == Permission.id)
        .filter(
            UserAppPerm.user_id == user_id,
            UserAppPerm.app_id == app.id,
            UserAppPerm.allow.is_(True),
            Permission.app_id == app.id  # ← AGREGADO: Filtro explícito por app
        )
        .all()
    )
    return {r[0] for r in rows}

def perms_via_roles(user_id: int, app_key: str) -> Set[str]:
    """
    CORREGIDO: Ahora filtra correctamente por app_id para obtener solo
    los permisos de la aplicación específica.
    """
    app = get_or_404_app(app_key)
    rows = (
        db.session.query(Permission.code)
        .join(RolePermission, RolePermission.perm_id == Permission.id)
        .join(UserAppRole, UserAppRole.role_id == RolePermission.role_id)
        .filter(
            UserAppRole.user_id == user_id,
            UserAppRole.app_id == app.id,
            Permission.app_id == app.id  # ← CRÍTICO: Filtro faltante agregado
        )
        .all()
    )
    return {r[0] for r in rows}

def effective_perms(user_id: int, app_key: str) -> Dict[str, Iterable[str]]:
    """Retorna detallado: roles, direct_perms, via_roles y union."""
    roles = user_roles_in_app(user_id, app_key)
    direct = user_direct_perms_in_app(user_id, app_key)
    via = perms_via_roles(user_id, app_key)
    effective = set(direct) | set(via)
    return {
        "roles": sorted(list(roles)),
        "direct_perms": sorted(list(direct)),
        "via_roles": sorted(list(via)),
        "effective": sorted(list(effective)),
    }

def list_roles() -> Iterable[str]:
    return [r[0] for r in db.session.query(Role.name).order_by(Role.name.asc()).all()]

def list_perms(app_key: str) -> Iterable[Dict]:
    app = get_or_404_app(app_key)
    rows = (
        db.session.query(Permission.code, Permission.name, Permission.description)
        .filter(Permission.app_id == app.id)
        .order_by(Permission.code.asc())
        .all()
    )
    return [{"code": c, "name": n, "description": d} for (c, n, d) in rows]

def has_any_assignment(user_id: int, app_key: str) -> bool:
    app = get_or_404_app(app_key)
    has_role = (
        db.session.query(UserAppRole)
        .filter_by(user_id=user_id, app_id=app.id)
        .count() > 0
    )
    has_perm = (
        db.session.query(UserAppPerm)
        .filter_by(user_id=user_id, app_id=app.id, allow=True)
        .count() > 0
    )
    return has_role or has_perm

def get_user_permissions_for_app(user_id: int, app_key: str) -> set[str]:
    """
    CORREGIDO: Obtiene el conjunto de todos los códigos de permiso efectivos 
    para un usuario en una app específica.
    Combina permisos directos y permisos heredados de roles.
    """
    app = App.query.filter_by(key=app_key).first()
    if not app:
        return set()

    # 1. Permisos directos (con filtro por app)
    direct_perms_query = (
        db.session.query(Permission.code)
        .join(UserAppPerm, UserAppPerm.perm_id == Permission.id)
        .filter(
            UserAppPerm.user_id == user_id,
            UserAppPerm.app_id == app.id,
            UserAppPerm.allow.is_(True),
            Permission.app_id == app.id  # ← AGREGADO: Filtro por app
        )
    )
    
    # 2. Permisos vía rol (con filtro por app)
    role_perms_query = (
        db.session.query(Permission.code)
        .join(RolePermission, RolePermission.perm_id == Permission.id)
        .join(UserAppRole, UserAppRole.role_id == RolePermission.role_id)
        .filter(
            UserAppRole.user_id == user_id,
            UserAppRole.app_id == app.id,
            Permission.app_id == app.id  # ← CRÍTICO: Filtro faltante agregado
        )
    )
    
    # Unir resultados y devolver un conjunto único
    direct_perms = {row[0] for row in direct_perms_query.all()}
    role_perms = {row[0] for row in role_perms_query.all()}
    
    return direct_perms.union(role_perms)