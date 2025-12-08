# itcj/core/services/authz_service.py
from __future__ import annotations
from typing import Iterable, Optional, Tuple, Set, Dict
from sqlalchemy.exc import IntegrityError
from itcj.core.extensions import db
from itcj.core.models.app import App
from itcj.core.models.role import Role
from itcj.core.models.permission import Permission
from itcj.core.models.role_permission import RolePermission
from itcj.core.models.user import User
from itcj.core.models.user_app_role import UserAppRole
from itcj.core.models.user_app_perm import UserAppPerm
from itcj.core.models.position import Position, UserPosition, PositionAppRole, PositionAppPerm

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
# Funciones de puestos organizacionales
# ---------------------------

def user_roles_via_positions(user_id: int, app_key: str) -> Set[str]:
    """Obtiene roles que el usuario tiene por sus puestos activos en una app"""
    app = get_or_404_app(app_key)
    rows = (
        db.session.query(Role.name)
        .join(PositionAppRole, PositionAppRole.role_id == Role.id)
        .join(UserPosition, UserPosition.position_id == PositionAppRole.position_id)
        .filter(
            UserPosition.user_id == user_id,
            UserPosition.is_active == True,
            PositionAppRole.app_id == app.id
        )
        .all()
    )
    return {r[0] for r in rows}

def user_perms_via_positions_direct(user_id: int, app_key: str) -> Set[str]:
    """Permisos directos asignados a los puestos del usuario"""
    app = get_or_404_app(app_key)
    rows = (
        db.session.query(Permission.code)
        .join(PositionAppPerm, PositionAppPerm.perm_id == Permission.id)
        .join(UserPosition, UserPosition.position_id == PositionAppPerm.position_id)
        .filter(
            UserPosition.user_id == user_id,
            UserPosition.is_active == True,
            PositionAppPerm.app_id == app.id,
            PositionAppPerm.allow == True,
            Permission.app_id == app.id
        )
        .all()
    )
    return {r[0] for r in rows}

def user_perms_via_position_roles(user_id: int, app_key: str) -> Set[str]:
    """Permisos que el usuario tiene vía roles de sus puestos"""
    app = get_or_404_app(app_key)
    rows = (
        db.session.query(Permission.code)
        .join(RolePermission, RolePermission.perm_id == Permission.id)
        .join(PositionAppRole, PositionAppRole.role_id == RolePermission.role_id)
        .join(UserPosition, UserPosition.position_id == PositionAppRole.position_id)
        .filter(
            UserPosition.user_id == user_id,
            UserPosition.is_active == True,
            PositionAppRole.app_id == app.id,
            Permission.app_id == app.id
        )
        .all()
    )
    return {r[0] for r in rows}

# ---------------------------
# Lecturas (MEJORADAS con puestos)
# ---------------------------

def _get_users_with_roles_in_app(app_key: str, role_names: list[str]) -> list[int]:
    """
    Obtiene usuarios con roles específicos en una app de forma eficiente.
    Considera roles directos Y roles heredados por puestos organizacionales.
    
    Args:
        app_key: Key de la aplicación ('helpdesk', 'itcj', etc.)
        role_names: Lista de nombres de roles a buscar (['secretary', 'admin'])
        
    Returns:
        Lista de user_ids que tienen alguno de los roles especificados
    """
    from sqlalchemy import union
    
    try:
        app = get_app_by_key(app_key)
        if not app:
            return []
        
        # Subquery 1: Usuarios con roles directos
        direct_roles = (
            db.session.query(User.id.label('user_id'))
            .join(UserAppRole, User.id == UserAppRole.user_id)
            .join(Role, UserAppRole.role_id == Role.id)
            .filter(
                User.is_active == True,
                UserAppRole.app_id == app.id,
                Role.name.in_(role_names)
            )
        )
        
        # Subquery 2: Usuarios con roles vía puestos
        position_roles = (
            db.session.query(User.id.label('user_id'))
            .join(UserPosition, User.id == UserPosition.user_id)
            .join(PositionAppRole, UserPosition.position_id == PositionAppRole.position_id)
            .join(Role, PositionAppRole.role_id == Role.id)
            .filter(
                User.is_active == True,
                UserPosition.is_active == True,
                PositionAppRole.app_id == app.id,
                Role.name.in_(role_names)
            )
        )
        
        # UNION de ambas subqueries (elimina duplicados automáticamente)
        combined_query = union(direct_roles, position_roles)
        result = db.session.execute(combined_query).fetchall()
        
        return [r[0] for r in result]
        
    except Exception as e:
        from flask import current_app
        current_app.logger.error(
            f"Error obteniendo usuarios con roles {role_names} en app {app_key}: {e}",
            exc_info=True
        )
        return []


def _get_users_with_position(position_codes: list[str]) -> list[int]:
    """
    Obtiene usuarios que tienen puestos organizacionales específicos activos.
    
    Args:
        position_codes: Lista de códigos de puestos (['secretary_cc', 'director_rh'])
        
    Returns:
        Lista de user_ids que tienen alguno de los puestos especificados activos
        
    Example:
        >>> # Notificar solo a la secretaria del Centro de Cómputo
        >>> users = _get_users_with_position(['secretary_cc'])
        >>> # Notificar a múltiples puestos
        >>> users = _get_users_with_position(['secretary_cc', 'director_cc'])
    """
    try:
        result = (
            db.session.query(User.id)
            .distinct()
            .join(UserPosition, User.id == UserPosition.user_id)
            .join(Position, UserPosition.position_id == Position.id)
            .filter(
                User.is_active == True,
                UserPosition.is_active == True,
                Position.is_active == True,
                Position.code.in_(position_codes)
            )
            .all()
        )
        
        return [r[0] for r in result]
        
    except Exception as e:
        from flask import current_app
        current_app.logger.error(
            f"Error obteniendo usuarios con puestos {position_codes}: {e}",
            exc_info=True
        )
        return []

def user_roles_in_app(user_id: int, app_key: str, include_positions: bool = True) -> Set[str]:
    """
    Obtiene roles del usuario en una app.
    Por defecto incluye roles heredados de puestos.
    """
    app = get_or_404_app(app_key)
    
    # Roles directos
    direct_roles = (
        db.session.query(Role.name)
        .join(UserAppRole, UserAppRole.role_id == Role.id)
        .filter(UserAppRole.user_id == user_id, UserAppRole.app_id == app.id)
        .all()
    )
    roles = {r[0] for r in direct_roles}
    
    # Roles vía puestos
    if include_positions:
        roles |= user_roles_via_positions(user_id, app_key)
    
    return roles

def user_direct_perms_in_app(user_id: int, app_key: str, include_positions: bool = True) -> Set[str]:
    """
    Permisos directos del usuario en una app.
    Por defecto incluye permisos directos de puestos.
    """
    app = get_or_404_app(app_key)
    
    # Permisos directos del usuario
    user_perms = (
        db.session.query(Permission.code)
        .join(UserAppPerm, UserAppPerm.perm_id == Permission.id)
        .filter(
            UserAppPerm.user_id == user_id,
            UserAppPerm.app_id == app.id,
            UserAppPerm.allow == True,
            Permission.app_id == app.id
        )
        .all()
    )
    perms = {r[0] for r in user_perms}
    
    # Permisos directos vía puestos
    if include_positions:
        perms |= user_perms_via_positions_direct(user_id, app_key)
    
    return perms

def perms_via_roles(user_id: int, app_key: str, include_positions: bool = True) -> Set[str]:
    """
    Permisos heredados de roles del usuario.
    Por defecto incluye permisos de roles heredados por puestos.
    """
    app = get_or_404_app(app_key)
    
    # Permisos vía roles directos del usuario
    user_role_perms = (
        db.session.query(Permission.code)
        .join(RolePermission, RolePermission.perm_id == Permission.id)
        .join(UserAppRole, UserAppRole.role_id == RolePermission.role_id)
        .filter(
            UserAppRole.user_id == user_id,
            UserAppRole.app_id == app.id,
            Permission.app_id == app.id
        )
        .all()
    )
    perms = {r[0] for r in user_role_perms}
    
    # Permisos vía roles de puestos
    if include_positions:
        perms |= user_perms_via_position_roles(user_id, app_key)
    
    return perms

def effective_perms(user_id: int, app_key: str, include_positions: bool = True) -> Dict[str, Iterable[str]]:
    """
    Retorna detallado: roles, direct_perms, via_roles y union.
    Por defecto incluye todo lo heredado de puestos.
    """
    roles = user_roles_in_app(user_id, app_key, include_positions)
    direct = user_direct_perms_in_app(user_id, app_key, include_positions)
    via = perms_via_roles(user_id, app_key, include_positions)
    effective = direct | via
    
    result = {
        "roles": sorted(list(roles)),
        "direct_perms": sorted(list(direct)),
        "via_roles": sorted(list(via)),
        "effective": sorted(list(effective)),
    }
    
    # Si se incluyeron puestos, agregar desglose
    if include_positions:
        result["roles_via_positions"] = sorted(list(user_roles_via_positions(user_id, app_key)))
        result["perms_via_positions_direct"] = sorted(list(user_perms_via_positions_direct(user_id, app_key)))
        result["perms_via_position_roles"] = sorted(list(user_perms_via_position_roles(user_id, app_key)))
    
    return result

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

def has_any_assignment(user_id: int, app_key: str, include_positions: bool = True) -> bool:
    """
    Verifica si el usuario tiene alguna asignación en la app.
    Por defecto incluye asignaciones vía puestos.
    """
    app = get_or_404_app(app_key)
    
    # Asignaciones directas
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
    
    if has_role or has_perm:
        return True
    
    # Asignaciones vía puestos
    if include_positions:
        has_position_role = (
            db.session.query(UserPosition)
            .join(PositionAppRole, PositionAppRole.position_id == UserPosition.position_id)
            .filter(
                UserPosition.user_id == user_id,
                UserPosition.is_active == True,
                PositionAppRole.app_id == app.id
            )
            .count() > 0
        )
        has_position_perm = (
            db.session.query(UserPosition)
            .join(PositionAppPerm, PositionAppPerm.position_id == UserPosition.position_id)
            .filter(
                UserPosition.user_id == user_id,
                UserPosition.is_active == True,
                PositionAppPerm.app_id == app.id,
                PositionAppPerm.allow == True
            )
            .count() > 0
        )
        
        return has_position_role or has_position_perm
    
    return False

def get_user_permissions_for_app(user_id: int, app_key: str, include_positions: bool = True) -> set[str]:
    """
    Obtiene el conjunto de todos los códigos de permiso efectivos 
    para un usuario en una app específica.
    Por defecto incluye permisos heredados de puestos.
    """
    return set(effective_perms(user_id, app_key, include_positions)["effective"])

def get_user_active_positions(user_id: int) -> list[dict]:
    """Obtiene los puestos activos del usuario"""
    positions = (
        db.session.query(Position, UserPosition)
        .join(UserPosition, UserPosition.position_id == Position.id)
        .filter(
            UserPosition.user_id == user_id,
            UserPosition.is_active == True,
            Position.is_active == True
        )
        .all()
    )
    
    return [
        {
            "id": pos.id,
            "code": pos.code,
            "title": pos.title,
            "department_id": pos.department_id,
            "start_date": user_pos.start_date.isoformat() if user_pos.start_date else None,
            "end_date": user_pos.end_date.isoformat() if user_pos.end_date else None
        }
        for pos, user_pos in positions
    ]

def user_has_position(user_id: int, position_codes: list[str]) -> bool:
    """Verifica si el usuario tiene alguno de los puestos especificados"""
    count = (
        db.session.query(UserPosition)
        .join(Position, Position.id == UserPosition.position_id)
        .filter(
            UserPosition.user_id == user_id,
            UserPosition.is_active == True,
            Position.code.in_(position_codes),
            Position.is_active == True
        )
        .count()
    )
    return count > 0