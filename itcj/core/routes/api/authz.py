# itcj/core/routes/api/authz.py
from flask import Blueprint, request, jsonify, current_app
from itcj.core.extensions import db
from itcj.core.models.app import App
from itcj.core.models.role import Role
from itcj.core.models.permission import Permission
from itcj.core.models.role_permission import RolePermission
from itcj.core.models.user import User
from itcj.core.utils.decorators import api_auth_required, api_role_required, api_app_required
from itcj.core.services import authz_service as svc


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
@api_app_required("itcj", perms=["core.apps.api.read"])
def list_apps():
    rows = db.session.query(App).order_by(App.key.asc()).all()
    data = [{"id":a.id,"key":a.key,"name":a.name,"is_active":a.is_active} for a in rows]
    return _ok(data)

@api_authz_bp.post("/apps")
@api_auth_required
@api_app_required("itcj", perms=["core.apps.api.create"])
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
@api_app_required("itcj", perms=["core.apps.api.update"])
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
@api_app_required("itcj", perms=["core.apps.api.delete"])
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
@api_app_required("itcj", perms=["core.roles.api.read"])
def list_roles():
    return _ok([{"name": r.name} for r in db.session.query(Role).order_by(Role.name.asc()).all()])

@api_authz_bp.post("/roles")
@api_auth_required
@api_app_required("itcj", perms=["core.roles.api.create"])
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
@api_app_required("itcj", perms=["core.roles.api.delete"])
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
@api_app_required("itcj", perms=["core.permissions.api.read.by_app"])
def list_perms(app_key):
    return _ok(svc.list_perms(app_key))

@api_authz_bp.post("/apps/<string:app_key>/perms")
@api_auth_required
@api_app_required("itcj", perms=["core.permissions.api.create"])
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
@api_app_required("itcj", perms=["core.permissions.api.delete"])
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
@api_app_required("itcj", perms=["core.roles.api.read.permissions"])
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
@api_app_required("itcj", perms=["core.roles.api.assign_permissions"])
def role_perms_replace(app_key, role_name):
    app = svc.get_or_404_app(app_key)
    role = db.session.query(Role).filter_by(name=role_name).first()
    if not role: return _bad("role_not_found", 404)
    
    payload = request.get_json(silent=True) or {}
    codes = payload.get("codes") or []

    # --- INICIO DE LA CORRECCIÓN ---

    # 1. Obtener los IDs de los permisos de esta app que están actualmente asignados al rol.
    perm_ids_to_delete = db.session.query(RolePermission.perm_id)\
        .join(Permission, Permission.id == RolePermission.perm_id)\
        .filter(
            RolePermission.role_id == role.id,
            Permission.app_id == app.id
        ).scalar_subquery()

    # 2. Ejecutar el DELETE en la tabla 'role_permissions' usando esos IDs, sin JOIN.
    db.session.query(RolePermission).filter(
        RolePermission.role_id == role.id,
        RolePermission.perm_id.in_(perm_ids_to_delete)
    ).delete(synchronize_session=False)

    # --- FIN DE LA CORRECCIÓN ---
    
    # El resto del código para insertar los nuevos permisos es correcto y no necesita cambios.
    if codes:
        perms = db.session.query(Permission).filter(
            Permission.app_id == app.id, Permission.code.in_(codes)
        ).all()
        db.session.bulk_save_objects([RolePermission(role_id=role.id, perm_id=p.id) for p in perms])
    
    db.session.commit()
    return _ok()

@api_authz_bp.post("/apps/<string:app_key>/roles/<string:role_name>/perms/<string:code>")
@api_auth_required
@api_app_required("itcj", perms=["core.roles.api.assign_permissions"])
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
@api_app_required("itcj", perms=["core.roles.api.assign_permissions"])
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
    
@api_authz_bp.get("/apps/<string:app_key>/users/<int:user_id>/roles")
@api_auth_required
@api_app_required("itcj", perms=["core.authz.api.read.user_roles"])
def user_roles(app_key, user_id):
    return _ok(sorted(list(svc.user_roles_in_app(user_id, app_key))))

@api_authz_bp.post("/apps/<string:app_key>/users/<int:user_id>/roles")
@api_auth_required
@api_app_required("itcj", perms=["core.authz.api.grant_roles"])
def user_roles_add(app_key, user_id):
    p = request.get_json(silent=True) or {}
    role_name = (p.get("role_name") or "").strip()
    if not role_name: return _bad("role_name_required")
    created = svc.grant_role(user_id, app_key, role_name)
    return _ok({"created": bool(created)})

@api_authz_bp.delete("/apps/<string:app_key>/users/<int:user_id>/roles/<string:role_name>")
@api_auth_required
@api_app_required("itcj", perms=["core.authz.api.revoke_roles"])
def user_roles_del(app_key, user_id, role_name):
    removed = svc.revoke_role(user_id, app_key, role_name)
    return _ok({"removed": bool(removed)})

@api_authz_bp.get("/apps/<string:app_key>/users/<int:user_id>/perms")
@api_auth_required
@api_app_required("itcj", perms=["core.authz.api.read.user_permissions"])
def user_perms(app_key, user_id):
    return _ok(sorted(list(svc.user_direct_perms_in_app(user_id, app_key))))

@api_authz_bp.post("/apps/<string:app_key>/users/<int:user_id>/perms")
@api_auth_required
@api_app_required("itcj", perms=["core.authz.api.grant_permissions"])
def user_perms_add(app_key, user_id):
    p = request.get_json(silent=True) or {}
    code = (p.get("code") or "").strip()
    allow = bool(p.get("allow", True))
    if not code: return _bad("code_required")
    changed = svc.grant_perm(user_id, app_key, code, allow=allow)
    return _ok({"updated": bool(changed)})

@api_authz_bp.delete("/apps/<string:app_key>/users/<int:user_id>/perms/<string:code>")
@api_auth_required
@api_app_required("itcj", perms=["core.authz.api.revoke_permissions"])
def user_perms_del(app_key, user_id, code):
    removed = svc.revoke_perm(user_id, app_key, code)
    return _ok({"removed": bool(removed)})

@api_authz_bp.get("/apps/<string:app_key>/users/<int:user_id>/effective-perms")
@api_auth_required
@api_app_required("itcj", perms=["core.authz.api.read.user_permissions"])
def user_effective(app_key, user_id):
    return _ok(svc.effective_perms(user_id, app_key))
