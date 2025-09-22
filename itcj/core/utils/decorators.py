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

def app_required(app_key: str,
                 roles: list[str] | None = None,
                 perms: list[str] | None = None,
                 any_of: bool = True,
                 allow_global_admin: bool = True):
    """Para rutas específicas (funciona en páginas y APIs)."""
    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            _check_app_access_or_abort(app_key, roles, perms, any_of, allow_global_admin)
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