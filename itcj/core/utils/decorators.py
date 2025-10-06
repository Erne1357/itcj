from functools import wraps
from flask import g, request, redirect, url_for, jsonify, current_app,abort
from .admit_window import is_student_window_open
import logging, os
from datetime import datetime
from itcj.core.extensions import db
from itcj.core.models.app import App
from itcj.core.models.role import Role
from itcj.core.models.permission import Permission
from itcj.core.models.user_app_role import UserAppRole
from itcj.core.models.user_app_perm import UserAppPerm
from itcj.core.models.role_permission import RolePermission
from itcj.core.models.role_permission import RolePermission
from itcj.core.models.position import UserPosition, PositionAppRole, PositionAppPerm, Position
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_

def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not g.get("current_user"):
            next_url = request.path
            return redirect(url_for("pages_core.pages_auth.login_page", next=next_url))
        return view(*args, **kwargs)
    return wrapper

def role_required_page(roles: list[str]):
    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            cu = g.get("current_user")
            if not cu:
                next_url = request.path
                return redirect(url_for("pages_core.pages_auth.login_page", next=next_url))
            if cu.get("role") not in roles:
                # 403 o redirigir a su home
                return redirect("/")
            return view(*args, **kwargs)
        return wrapper
    return deco

# Para endpoints JSON / APIs
def api_auth_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not g.get("current_user"):
            return jsonify({"error": "unauthorized"}), 401
        return view(*args, **kwargs)
    return wrapper

def api_role_required(roles: list[str]):
    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            cu = g.get("current_user")
            if not cu:
                return jsonify({"error": "unauthorized"}), 401
            if cu.get("role") not in roles:
                return jsonify({"error": "forbidden"}), 403
            return view(*args, **kwargs)
        return wrapper
    return deco

# Decorador para verificar si el usuario debe cambiar su contraseña
def pw_changed_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        cu = g.get("current_user")
        # Solo aplica para personal que no sea estudiante
        if cu and cu.get("role") != "student":
            # Debes tener una función que verifique el estado, por ejemplo:
            from itcj.core.models.user import User
            user = User.query.filter_by(id=cu["sub"]).first()
            if user and getattr(user, "must_change_password", False):
                # Redirige a dashboard si no ha cambiado su contraseña
                return redirect(url_for("pages_core.pages_dashboard.dashboard"))
        return view(*args, **kwargs)
    return wrapper

def student_app_closed(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_student_window_open():
            return redirect(url_for('agendatec_pages.student_pages.student_close'))
        return view(*args, **kwargs)
    return wrapper

def api_closed(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_student_window_open():
            return jsonify({'status':'error','message':'El período de admisión ha finalizado.'}), 423
        return view(*args, **kwargs)
    return wrapper

def app_required(app_key: str, roles: list[str] | None = None,
                 perms: list[str] | None = None, any_of=True,
                 allow_global_admin=True):
    roles = set(roles or [])
    perms = set(perms or [])
    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            cu = g.get("current_user")
            if not cu:
                abort(401)

            app = db.session.query(App).filter_by(key=app_key).first()
            if not app:
                abort(404)

            # Admin global por role del JWT
            if allow_global_admin and cu.get("role") == "admin":
                return view(*args, **kwargs)

            uid = int(cu["sub"])

            # ¿Tiene algo en esta app?
            has_any = (
                db.session.query(UserAppRole)
                  .filter_by(user_id=uid, app_id=app.id).count() > 0
                or
                db.session.query(UserAppPerm)
                  .filter_by(user_id=uid, app_id=app.id, allow=True).count() > 0
            )
            if not has_any:
                abort(403)

            # ¿Roles requeridos?
            if roles:
                has_role = (
                    db.session.query(UserAppRole)
                      .join(Role, Role.id == UserAppRole.role_id)
                      .filter(UserAppRole.user_id == uid,
                              UserAppRole.app_id  == app.id,
                              Role.name.in_(roles)).count() > 0
                )
                if not has_role and (not perms or not any_of):
                    abort(403)

            # ¿Permisos requeridos?
            if perms:
                # Directo
                direct_ok = (
                    db.session.query(UserAppPerm)
                      .join(Permission, Permission.id == UserAppPerm.perm_id)
                      .filter(UserAppPerm.user_id == uid,
                              UserAppPerm.app_id  == app.id,
                              UserAppPerm.allow == True,
                              Permission.code.in_(perms)).count() > 0
                )
                # Vía rol
                via_role_ok = (
                    db.session.query(RolePermission)
                      .join(Permission, Permission.id == RolePermission.perm_id)
                      .join(UserAppRole, UserAppRole.role_id == RolePermission.role_id)
                      .filter(UserAppRole.user_id == uid,
                              UserAppRole.app_id  == app.id,
                              Permission.code.in_(perms)).count() > 0
                )
                ok = (direct_ok or via_role_ok) if any_of else (direct_ok and via_role_ok)
                if not ok:
                    abort(403)

            return view(*args, **kwargs)
        return wrapper
    return deco

def _check_app_access_or_abort(app_key: str,
                               roles: list[str] | None = None,
                               perms: list[str] | None = None,
                               any_of: bool = True,
                               allow_global_admin: bool = True) -> None:
    """Lanza 401/403/404 si no cumple. Reusada por app_required y guard_blueprint."""
    cu = g.get("current_user")
    if not cu:
        abort(401)

    app = db.session.query(App).filter_by(key=app_key, is_active=True).first()
    if not app:
        abort(404)

    # Admin global por rol del JWT (legacy)
    if allow_global_admin and cu.get("role") == "admin":
        return

    uid = int(cu["sub"])

    # ¿Tiene algo en esta app?
    has_any = (
        db.session.query(UserAppRole).filter_by(user_id=uid, app_id=app.id).count() > 0
        or
        db.session.query(UserAppPerm).filter_by(user_id=uid, app_id=app.id, allow=True).count() > 0
    )
    if not has_any:
        abort(403)

    roles = set(roles or [])
    perms = set(perms or [])

    # ¿Roles requeridos?
    if roles:
        has_role = (
            db.session.query(UserAppRole)
              .join(Role, Role.id == UserAppRole.role_id)
              .filter(UserAppRole.user_id == uid,
                      UserAppRole.app_id == app.id,
                      Role.name.in_(roles))
              .count() > 0
        )
        if not has_role and (not perms or not any_of):
            abort(403)

    # ¿Permisos requeridos?
    if perms:
        # Directos
        direct_ok = (
            db.session.query(UserAppPerm)
              .join(Permission, Permission.id == UserAppPerm.perm_id)
              .filter(UserAppPerm.user_id == uid,
                      UserAppPerm.app_id == app.id,
                      UserAppPerm.allow.is_(True),
                      Permission.code.in_(perms))
              .count() > 0
        )
        # Vía roles
        via_role_ok = (
            db.session.query(RolePermission)
              .join(Permission, Permission.id == RolePermission.perm_id)
              .join(UserAppRole, UserAppRole.role_id == RolePermission.role_id)
              .filter(UserAppRole.user_id == uid,
                      UserAppRole.app_id == app.id,
                      Permission.code.in_(perms))
              .count() > 0
        )
        ok = (direct_ok or via_role_ok) if any_of else (direct_ok and via_role_ok)
        if not ok:
            abort(403)
def api_app_required(app_key: str, roles: list[str] | None = None, perms: list[str] | None = None):
    """Decorador unificado para proteger APIs, respondiendo con JSON."""
    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            try:
                _check_app_access_or_abort(app_key, roles, perms, any_of=True)
            except Exception as e:
                code = getattr(e, 'code', 500)
                if code == 401: return jsonify({"error": "unauthorized"}), 401
                if code == 403: return jsonify({"error": "forbidden"}), 403
                if code == 404: return jsonify({"error": "not_found"}), 404
                raise e
            return view(*args, **kwargs)
        return wrapper
    return deco

def guard_blueprint(bp,
                    app_key: str,
                    *,
                    roles: list[str] | None = None,
                    perms: list[str] | None = None,
                    any_of: bool = True,
                    allow_global_admin: bool = True):
    """Protege TODO el blueprint con una sola línea."""
    @bp.before_request
    def _guard():
        _check_app_access_or_abort(app_key, roles, perms, any_of, allow_global_admin)

def _check_app_access_enhanced(app_key: str,
                               roles: list[str] | None = None,
                               perms: list[str] | None = None,
                               positions: list[str] | None = None,
                               any_of: bool = True,
                               allow_global_admin: bool = True) -> None:
    """
    Verificación mejorada que incluye puestos organizacionales.
    
    Args:
        positions: Lista de códigos de puesto (ej: ['coord_sistemas', 'jefe_depto'])
    """
    cu = g.get("current_user")
    if not cu:
        abort(401)

    app = db.session.query(App).filter_by(key=app_key, is_active=True).first()
    if not app:
        abort(404)

    # Admin global por rol del JWT (legacy)
    if allow_global_admin and cu.get("role") == "admin":
        return

    uid = int(cu["sub"])
    roles = set(roles or [])
    perms = set(perms or [])
    positions = set(positions or [])

    # Verificar acceso por PUESTOS ORGANIZACIONALES
    if positions:
        has_position = (
            db.session.query(UserPosition)
            .join(Position, Position.id == UserPosition.position_id)
            .filter(
                UserPosition.user_id == uid,
                UserPosition.is_active == True,
                Position.code.in_(positions),
                Position.is_active == True
            )
            .count() > 0
        )
        
        if has_position:
            return  # Acceso concedido por puesto

    # Verificar si tiene ALGUNA asignación directa (usuario-app)
    has_user_assignment = (
        db.session.query(UserAppRole).filter_by(user_id=uid, app_id=app.id).count() > 0
        or
        db.session.query(UserAppPerm).filter_by(user_id=uid, app_id=app.id, allow=True).count() > 0
    )

    # Verificar si tiene asignaciones VIA PUESTOS
    has_position_assignment = (
        db.session.query(UserPosition)
        .join(PositionAppRole, PositionAppRole.position_id == UserPosition.position_id)
        .filter(
            UserPosition.user_id == uid,
            UserPosition.is_active == True,
            PositionAppRole.app_id == app.id
        )
        .union(
            db.session.query(UserPosition)
            .join(PositionAppPerm, PositionAppPerm.position_id == UserPosition.position_id)
            .filter(
                UserPosition.user_id == uid,
                UserPosition.is_active == True,
                PositionAppPerm.app_id == app.id,
                PositionAppPerm.allow == True
            )
        )
        .count() > 0
    )

    if not (has_user_assignment or has_position_assignment):
        abort(403)

    # Si especificó roles, verificar roles (directos + vía puestos)
    if roles:
        has_direct_role = (
            db.session.query(UserAppRole)
            .join(Role, Role.id == UserAppRole.role_id)
            .filter(
                UserAppRole.user_id == uid,
                UserAppRole.app_id == app.id,
                Role.name.in_(roles)
            )
            .count() > 0
        )
        
        has_position_role = (
            db.session.query(UserPosition)
            .join(PositionAppRole, PositionAppRole.position_id == UserPosition.position_id)
            .join(Role, Role.id == PositionAppRole.role_id)
            .filter(
                UserPosition.user_id == uid,
                UserPosition.is_active == True,
                PositionAppRole.app_id == app.id,
                Role.name.in_(roles)
            )
            .count() > 0
        )
        
        if not (has_direct_role or has_position_role) and (not perms or not any_of):
            abort(403)

    # Si especificó permisos, verificar permisos (directos + vía roles + vía puestos)
    if perms:
        # Permisos directos del usuario
        direct_user_perms = (
            db.session.query(UserAppPerm)
            .join(Permission, Permission.id == UserAppPerm.perm_id)
            .filter(
                UserAppPerm.user_id == uid,
                UserAppPerm.app_id == app.id,
                UserAppPerm.allow == True,
                Permission.code.in_(perms)
            )
            .count() > 0
        )
        
        # Permisos vía roles del usuario
        via_user_roles = (
            db.session.query(RolePermission)
            .join(Permission, Permission.id == RolePermission.perm_id)
            .join(UserAppRole, UserAppRole.role_id == RolePermission.role_id)
            .filter(
                UserAppRole.user_id == uid,
                UserAppRole.app_id == app.id,
                Permission.code.in_(perms)
            )
            .count() > 0
        )
        
        # Permisos directos vía puestos
        direct_position_perms = (
            db.session.query(UserPosition)
            .join(PositionAppPerm, PositionAppPerm.position_id == UserPosition.position_id)
            .join(Permission, Permission.id == PositionAppPerm.perm_id)
            .filter(
                UserPosition.user_id == uid,
                UserPosition.is_active == True,
                PositionAppPerm.app_id == app.id,
                PositionAppPerm.allow == True,
                Permission.code.in_(perms)
            )
            .count() > 0
        )
        
        # Permisos vía roles de puestos
        via_position_roles = (
            db.session.query(UserPosition)
            .join(PositionAppRole, PositionAppRole.position_id == UserPosition.position_id)
            .join(RolePermission, RolePermission.role_id == PositionAppRole.role_id)
            .join(Permission, Permission.id == RolePermission.perm_id)
            .filter(
                UserPosition.user_id == uid,
                UserPosition.is_active == True,
                PositionAppRole.app_id == app.id,
                Permission.code.in_(perms)
            )
            .count() > 0
        )
        
        has_any_perm = (direct_user_perms or via_user_roles or 
                       direct_position_perms or via_position_roles)
        
        if not has_any_perm:
            abort(403)

def app_required_enhanced(app_key: str,
                         roles: list[str] | None = None,
                         perms: list[str] | None = None,
                         positions: list[str] | None = None,
                         any_of: bool = True,
                         allow_global_admin: bool = True):
    """
    Decorador mejorado que soporta verificación por puestos organizacionales.
    
    Args:
        app_key: Clave de la aplicación
        roles: Roles globales requeridos
        perms: Permisos específicos requeridos  
        positions: Códigos de puestos organizacionales (ej: ['coord_sistemas'])
        any_of: Si True, cualquier condición cumplida da acceso
        allow_global_admin: Si True, admin global siempre tiene acceso
    
    Ejemplo:
        @app_required_enhanced("agendatec", positions=["coord_sistemas", "coord_industrial"])
        def coordinator_only_view():
            pass
            
        @app_required_enhanced("agendatec", 
                              roles=["coordinator"], 
                              positions=["jefe_depto"],
                              any_of=True)
        def coord_or_boss_view():
            pass
    """
    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            _check_app_access_enhanced(app_key, roles, perms, positions, any_of, allow_global_admin)
            return view(*args, **kwargs)
        return wrapper
    return deco

def guard_blueprint_enhanced(bp,
                           app_key: str,
                           *,
                           roles: list[str] | None = None,
                           perms: list[str] | None = None,
                           positions: list[str] | None = None,
                           any_of: bool = True,
                           allow_global_admin: bool = True):
    """Protege TODO un blueprint con verificación mejorada incluyendo puestos"""
    @bp.before_request
    def _guard():
        _check_app_access_enhanced(app_key, roles, perms, positions, any_of, allow_global_admin)

# Funciones de utilidad para obtener permisos del usuario actual
def get_current_user_permissions(app_key: str) -> set[str]:
    """Obtiene todos los permisos efectivos del usuario actual en una app"""
    cu = g.get("current_user")
    if not cu:
        return set()
    
    uid = int(cu["sub"])
    
    # Importar aquí para evitar circular imports
    from itcj.core.services.authz_service import effective_perms
    from itcj.core.services.positions_service import get_position_effective_permissions
    
    # Permisos directos del usuario
    user_perms = effective_perms(uid, app_key).get('effective', [])
    
    # Permisos vía puestos
    position_perms = get_position_effective_permissions(uid, app_key)
    
    return set(user_perms) | position_perms

def get_current_user_positions() -> list[dict]:
    """Obtiene los puestos activos del usuario actual"""
    cu = g.get("current_user")
    if not cu:
        return []
    
    uid = int(cu["sub"])
    
    from itcj.core.services.positions_service import get_user_active_positions
    return get_user_active_positions(uid)

def has_position(position_codes: list[str]) -> bool:
    """Verifica si el usuario actual tiene alguno de los puestos especificados"""
    user_positions = get_current_user_positions()
    user_position_codes = {pos['code'] for pos in user_positions}
    return bool(set(position_codes) & user_position_codes)

# Mantener compatibilidad con decoradores anteriores
app_required = app_required_enhanced
guard_blueprint = guard_blueprint_enhanced