# itcj/core/routes/api/authz.py
from flask import Blueprint, request, jsonify, current_app
from itcj.core.extensions import db
from itcj.core.models.app import App
from itcj.core.models.role import Role
from itcj.core.models.permission import Permission
from itcj.core.models.role_permission import RolePermission
from itcj.core.models.user import User
from itcj.core.utils.decorators import api_auth_required, api_role_required
from itcj.core.services import authz_service as svc
from sqlalchemy.exc import IntegrityError
from itcj.core.utils.security import hash_nip

api_authz_bp = Blueprint("api_authz_bp", __name__)

# ---------------------------
# Helpers
# ---------------------------

def _ok(data=None, status=200):
    if data is not None:
        return jsonify({"status": "ok", "data": data}), status
    else:
        return "", 204
    
def _bad(msg="bad_request", status=400):
    return jsonify({"status":"error","error":msg}), status

# ---------------------------
# Apps
# ---------------------------

@api_authz_bp.get("/apps")
@api_auth_required
@api_role_required(["admin"])  # admin global ve todo
def list_apps():
    rows = db.session.query(App).order_by(App.key.asc()).all()
    data = [{"id":a.id,"key":a.key,"name":a.name,"is_active":a.is_active} for a in rows]
    return _ok(data)

@api_authz_bp.post("/apps")
@api_auth_required
@api_role_required(["admin"])
def create_app():
    payload = request.get_json(silent=True) or {}
    key = (payload.get("key") or "").strip()
    name = (payload.get("name") or "").strip()
    is_active = bool(payload.get("is_active", True))
    if not key or not name:
        return _bad("key_and_name_required")
    if db.session.query(App).filter_by(key=key).first():
        return _bad("app_key_exists", 409)
    a = App(key=key, name=name, is_active=is_active)
    db.session.add(a); db.session.commit()
    return _ok({"id":a.id,"key":a.key,"name":a.name,"is_active":a.is_active}, 201)

@api_authz_bp.patch("/apps/<string:app_key>")
@api_auth_required
@api_role_required(["admin"])
def update_app(app_key):
    a = db.session.query(App).filter_by(key=app_key).first()
    if not a: return _bad("not_found", 404)
    p = request.get_json(silent=True) or {}
    if "name" in p: a.name = (p["name"] or "").strip() or a.name
    if "is_active" in p: a.is_active = bool(p["is_active"])
    db.session.commit()
    return _ok({"id":a.id,"key":a.key,"name":a.name,"is_active":a.is_active})

@api_authz_bp.delete("/apps/<string:app_key>")
@api_auth_required
@api_role_required(["admin"])
def delete_app(app_key):
    a = db.session.query(App).filter_by(key=app_key).first()
    if not a: return _bad("not_found", 404)
    db.session.delete(a); db.session.commit()
    return _ok()

# ---------------------------
# Roles (globales)
# ---------------------------

@api_authz_bp.get("/roles")
@api_auth_required
@api_role_required(["admin"])
def list_roles():
    return _ok([{"name": r.name} for r in db.session.query(Role).order_by(Role.name.asc()).all()])

@api_authz_bp.post("/roles")
@api_auth_required
@api_role_required(["admin"])
def create_role():
    p = request.get_json(silent=True) or {}
    name = (p.get("name") or "").strip()
    if not name: return _bad("name_required")
    if db.session.query(Role).filter_by(name=name).first():
        return _bad("role_exists", 409)
    r = Role(name=name)
    db.session.add(r); db.session.commit()
    return _ok({"name": r.name}, 201)

@api_authz_bp.delete("/roles/<string:role_name>")
@api_auth_required
@api_role_required(["admin"])
def delete_role(role_name):
    r = db.session.query(Role).filter_by(name=role_name).first()
    if not r: return _bad("not_found", 404)
    db.session.delete(r); db.session.commit()
    return _ok()

# ---------------------------
# Permisos por App
# ---------------------------

@api_authz_bp.get("/apps/<string:app_key>/perms")
@api_auth_required
@api_role_required(["admin"])
def list_perms(app_key):
    return _ok(svc.list_perms(app_key))

@api_authz_bp.post("/apps/<string:app_key>/perms")
@api_auth_required
@api_role_required(["admin"])
def create_perm(app_key):
    app = svc.get_or_404_app(app_key)
    p = request.get_json(silent=True) or {}
    code = (p.get("code") or "").strip()
    name = (p.get("name") or "").strip()
    desc = (p.get("description") or "").strip() or None
    if not code or not name: return _bad("code_and_name_required")
    if db.session.query(Permission).filter_by(app_id=app.id, code=code).first():
        return _bad("permission_exists", 409)
    perm = Permission(app_id=app.id, code=code, name=name, description=desc)
    db.session.add(perm); db.session.commit()
    return _ok({"code":perm.code,"name":perm.name,"description":perm.description}, 201)

@api_authz_bp.delete("/apps/<string:app_key>/perms/<string:code>")
@api_auth_required
@api_role_required(["admin"])
def delete_perm(app_key, code):
    app = svc.get_or_404_app(app_key)
    perm = db.session.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not perm: return _bad("not_found", 404)
    db.session.delete(perm); db.session.commit()
    return _ok()

# ---------------------------
# Role ⇄ Permission (por App)
# ---------------------------

@api_authz_bp.get("/apps/<string:app_key>/roles/<string:role_name>/perms")
@api_auth_required
@api_role_required(["admin"])
def role_perms(app_key, role_name):
    app = svc.get_or_404_app(app_key)
    role = db.session.query(Role).filter_by(name=role_name).first()
    if not role: return _bad("role_not_found", 404)
    rows = (
        db.session.query(Permission.code)
        .join(RolePermission, RolePermission.perm_id == Permission.id)
        .filter(RolePermission.role_id == role.id, Permission.app_id == app.id)
        .order_by(Permission.code.asc())
        .all()
    )
    return _ok([r[0] for r in rows])

@api_authz_bp.put("/apps/<string:app_key>/roles/<string:role_name>/perms")
@api_auth_required
@api_role_required(["admin"])
def role_perms_replace(app_key, role_name):
    app = svc.get_or_404_app(app_key)
    role = db.session.query(Role).filter_by(name=role_name).first()
    if not role: return _bad("role_not_found", 404)
    payload = request.get_json(silent=True) or {}
    codes = payload.get("codes") or []
    # borrar los existentes de esta app
    db.session.query(RolePermission).join(Permission).filter(
        RolePermission.role_id == role.id, Permission.app_id == app.id
    ).delete(synchronize_session=False)
    # insertar los nuevos
    if codes:
        perms = db.session.query(Permission).filter(
            Permission.app_id == app.id, Permission.code.in_(codes)
        ).all()
        db.session.bulk_save_objects([RolePermission(role_id=role.id, perm_id=p.id) for p in perms])
    db.session.commit()
    return _ok()

@api_authz_bp.post("/apps/<string:app_key>/roles/<string:role_name>/perms/<string:code>")
@api_auth_required
@api_role_required(["admin"])
def role_perm_add(app_key, role_name, code):
    app = svc.get_or_404_app(app_key)
    role = db.session.query(Role).filter_by(name=role_name).first()
    if not role: return _bad("role_not_found", 404)
    perm = db.session.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not perm: return _bad("perm_not_found", 404)
    if not db.session.query(RolePermission).filter_by(role_id=role.id, perm_id=perm.id).first():
        db.session.add(RolePermission(role_id=role.id, perm_id=perm.id)); db.session.commit()
    return _ok()

@api_authz_bp.delete("/apps/<string:app_key>/roles/<string:role_name>/perms/<string:code>")
@api_auth_required
@api_role_required(["admin"])
def role_perm_remove(app_key, role_name, code):
    app = svc.get_or_404_app(app_key)
    role = db.session.query(Role).filter_by(name=role_name).first()
    if not role: return _bad("role_not_found", 404)
    perm = db.session.query(Permission).filter_by(app_id=app.id, code=code).first()
    if not perm: return _bad("perm_not_found", 404)
    db.session.query(RolePermission).filter_by(role_id=role.id, perm_id=perm.id).delete()
    db.session.commit()
    return _ok()

# ---------------------------
# Usuario ⇄ Rol / Permiso por App
# ---------------------------
@api_authz_bp.post("/users")
# @api_permission_required(app_key="core", perms=["users.create"]) # Usarías esto con el nuevo sistema de permisos
def create_user():
    """Crea un nuevo usuario (estudiante o personal)"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid input"}), 400

    full_name = data.get("full_name")
    email = data.get("email")
    user_type = data.get("user_type")
    password = data.get("password")

    if not all([full_name, user_type, password]):
        return jsonify({"error": "Missing required fields"}), 400

    # Determina el rol base del sistema
    if user_type == "student":
        role_name = "student"
        control_number = data.get("control_number")
        if not control_number or len(control_number) != 8:
            return jsonify({"error": "Valid control number is required for students"}), 400
        # Validar si ya existe
        if User.query.filter_by(control_number=control_number).first():
            return jsonify({"error": "Control number already exists"}), 409
        
    elif user_type == "staff":
        role_name = "staff" # O un rol por defecto que tengas
        username = data.get("username")
        if not username:
            return jsonify({"error": "Username is required for staff"}), 400
        # Validar si ya existe
        if User.query.filter_by(username=username).first():
            return jsonify({"error": "Username already exists"}), 409
    else:
        return jsonify({"error": "Invalid user type"}), 400

    role = Role.query.filter_by(name=role_name).first()
    if not role:
        return jsonify({"error": f"Default role '{role_name}' not found"}), 500

    try:
        new_user = User(
            full_name=full_name,
            email=email,
            role_id=role.id,
            nip_hash=hash_nip(password), # ¡Importante! Siempre hashear la contraseña/NIP
            control_number=data.get("control_number") if user_type == 'student' else None,
            username=data.get("username") if user_type == 'staff' else None,
            must_change_password=(user_type == 'staff') # Forzar cambio de contraseña para personal
        )
        db.session.add(new_user)
        db.session.commit()
        
        # Prepara una respuesta con los datos del usuario creado
        user_data = {
            "id": new_user.id,
            "full_name": new_user.full_name,
            "email": new_user.email,
            "username": new_user.username,
            "control_number": new_user.control_number,
            "is_active": new_user.is_active
        }
        return jsonify({"message": "User created successfully", "user": user_data}), 201

    except IntegrityError as e:
        db.session.rollback()
        return jsonify({"error": "Database integrity error. User might already exist."}), 409
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating user: {e}")
        return jsonify({"error": "An internal error occurred"}), 500
    
@api_authz_bp.get("/apps/<string:app_key>/users/<int:user_id>/roles")
@api_auth_required
@api_role_required(["admin"])
def user_roles(app_key, user_id):
    return _ok(sorted(list(svc.user_roles_in_app(user_id, app_key))))

@api_authz_bp.post("/apps/<string:app_key>/users/<int:user_id>/roles")
@api_auth_required
@api_role_required(["admin"])
def user_roles_add(app_key, user_id):
    p = request.get_json(silent=True) or {}
    role_name = (p.get("role_name") or "").strip()
    if not role_name: return _bad("role_name_required")
    created = svc.grant_role(user_id, app_key, role_name)
    return _ok({"created": bool(created)})

@api_authz_bp.delete("/apps/<string:app_key>/users/<int:user_id>/roles/<string:role_name>")
@api_auth_required
@api_role_required(["admin"])
def user_roles_del(app_key, user_id, role_name):
    removed = svc.revoke_role(user_id, app_key, role_name)
    return _ok({"removed": bool(removed)})

@api_authz_bp.get("/apps/<string:app_key>/users/<int:user_id>/perms")
@api_auth_required
@api_role_required(["admin"])
def user_perms(app_key, user_id):
    return _ok(sorted(list(svc.user_direct_perms_in_app(user_id, app_key))))

@api_authz_bp.post("/apps/<string:app_key>/users/<int:user_id>/perms")
@api_auth_required
@api_role_required(["admin"])
def user_perms_add(app_key, user_id):
    p = request.get_json(silent=True) or {}
    code = (p.get("code") or "").strip()
    allow = bool(p.get("allow", True))
    if not code: return _bad("code_required")
    changed = svc.grant_perm(user_id, app_key, code, allow=allow)
    return _ok({"updated": bool(changed)})

@api_authz_bp.delete("/apps/<string:app_key>/users/<int:user_id>/perms/<string:code>")
@api_auth_required
@api_role_required(["admin"])
def user_perms_del(app_key, user_id, code):
    removed = svc.revoke_perm(user_id, app_key, code)
    return _ok({"removed": bool(removed)})

@api_authz_bp.get("/apps/<string:app_key>/users/<int:user_id>/effective-perms")
@api_auth_required
@api_role_required(["admin"])
def user_effective(app_key, user_id):
    return _ok(svc.effective_perms(user_id, app_key))
