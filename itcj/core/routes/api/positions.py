# itcj/core/routes/api/positions.py
from flask import Blueprint, request, jsonify, g, current_app
from itcj.core.utils.decorators import api_auth_required, api_role_required, api_app_required
from itcj.core.services import positions_service as svc
from itcj.core.extensions import db
from datetime import date, datetime

api_positions_bp = Blueprint("api_positions_bp", __name__)

def _ok(data=None, status=200):
    return (jsonify({"status": "ok", "data": data}) if data is not None else ("", 204)), status

def _bad(msg="bad_request", status=400):
    return jsonify({"status": "error", "error": msg}), status

# ---------------------------
# CRUD de Puestos
# ---------------------------

@api_positions_bp.get("")
@api_auth_required
@api_app_required("itcj", perms=["core.positions.api.read"])
def list_positions():
    """Lista todos los puestos organizacionales"""
    department = request.args.get("department")
    positions = svc.list_positions(department)
    
    data = [{
        "id": p.id,
        "code": p.code,
        "title": p.title,
        "description": p.description,
        "email": p.email,
        "department_id": p.department_id,
        "is_active": p.is_active,
        "allows_multiple": p.allows_multiple,
        "current_user": svc.get_position_current_user(p.id)
    } for p in positions]
    
    return _ok(data)

@api_positions_bp.get("/<int:position_id>")
@api_auth_required
@api_app_required("itcj", perms=["core.positions.api.read"])
def get_position(position_id):
    """Obtiene un puesto específico con toda su información"""
    try:
        position = svc.get_position_by_id(position_id)
        if not position:
            return _bad("not_found", 404)
        
        # Obtener usuarios asignados
        current_users = svc.get_position_current_users(position_id)
        
        # Obtener asignaciones de apps
        assignments = svc.get_position_assignments(position_id)
        
        return _ok({
            "id": position.id,
            "code": position.code,
            "title": position.title,
            "description": position.description,
            "email": position.email,
            "department_id": position.department_id,
            "is_active": position.is_active,
            "allows_multiple": position.allows_multiple,
            "current_users": current_users,
            "assignments": assignments
        })
    except Exception as e:
        current_app.logger.error(f"Error getting position: {e}")
        return _bad(str(e), 500)

@api_positions_bp.post("")
@api_auth_required
@api_app_required("itcj", perms=["core.positions.api.create"])
def create_position():
    """Crea un nuevo puesto organizacional"""
    payload = request.get_json(silent=True) or {}
    code = (payload.get("code") or "").strip()
    title = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip() or None
    email = (payload.get("email") or "").strip() or None
    department_id = payload.get("department_id")  
    allows_multiple = bool(payload.get("allows_multiple", False))
    is_active = bool(payload.get("is_active", True))

    if not code or not title:
        return _bad("code_and_title_required")
    
    try:
        position = svc.create_position(
            code=code, 
            title=title, 
            description=description, 
            email=email,
            department_id=department_id, 
            allows_multiple=allows_multiple, 
            is_active=is_active
        )
        return _ok({
            "id": position.id,
            "code": position.code,
            "title": position.title,
            "description": position.description,
            "email": position.email,
            "department_id": position.department_id,
            "is_active": position.is_active,
            "allows_multiple": position.allows_multiple
        }, 201)
    except ValueError as e:
        return _bad(str(e), 409)

@api_positions_bp.patch("/<int:position_id>")
@api_auth_required
@api_app_required("itcj", perms=["core.positions.api.update"])
def update_position(position_id):
    """Actualiza un puesto organizacional"""
    payload = request.get_json(silent=True) or {}
    
    try:
        position = svc.update_position(position_id, **{
            k: v for k, v in payload.items() 
            if k in ['title', 'description', 'department_id', 'is_active', 'allows_multiple', 'email']
        })
        return _ok({
            "id": position.id,
            "code": position.code,
            "title": position.title,
            "description": position.description,
            "email": position.email,
            "department_id": position.department_id,
            "allows_multiple": position.allows_multiple,
            "is_active": position.is_active,
            "department": {
                "id": position.department.id,
                "name": position.department.name,
                "code": position.department.code
            } if position.department else None
        })
    except ValueError as e:
        return _bad(str(e), 404)

@api_positions_bp.delete("/<int:position_id>")
@api_auth_required
@api_app_required("itcj", perms=["core.positions.api.delete"])
def delete_position(position_id):
    """Elimina un puesto organizacional SOLO si no tiene usuarios asignados"""
    try:
        from itcj.core.models.position import UserPosition
        
        # Verificar si hay usuarios asignados
        active_assignments = UserPosition.query.filter_by(
            position_id=position_id,
            is_active=True
        ).count()
        
        if active_assignments > 0:
            return _bad("position_has_active_users", 409)
        
        # Verificar si el puesto existe
        position = svc.get_position_by_id(position_id)
        if not position:
            return _bad("not_found", 404)
        
        # Eliminar el puesto
        if svc.delete_position(position_id):
            return _ok({"deleted": True})
        
        return _bad("deletion_failed", 500)
        
    except Exception as e:
        current_app.logger.error(f"Error deleting position: {e}")
        return _bad(str(e), 500)

# ---------------------------
# Asignación de Usuarios a Puestos
# ---------------------------

@api_positions_bp.get("/<int:position_id>/user")
@api_auth_required
@api_app_required("itcj", perms=["core.positions.api.read.assignments"])
def get_position_current_user(position_id):
    """Obtiene el usuario actualmente asignado al puesto"""
    user_data = svc.get_position_current_user(position_id)
    return _ok(user_data)

@api_positions_bp.get("/<int:position_id>/users")
@api_auth_required
@api_app_required("itcj", perms=["core.positions.api.read.assignments"])
def get_position_current_users_list(position_id):
    """Obtiene TODOS los usuarios asignados al puesto"""
    users_data = svc.get_position_current_users(position_id)
    return _ok(users_data)

@api_positions_bp.post("/<int:position_id>/assign-user")
@api_auth_required
@api_app_required("itcj", perms=["core.positions.api.assign_users"])
def assign_user_to_position(position_id):
    """Asigna un usuario a un puesto"""
    payload = request.get_json(silent=True) or {}
    user_id = payload.get("user_id")
    notes = (payload.get("notes") or "").strip() or None
    start_date_str = payload.get("start_date")
    
    if not user_id:
        return _bad("user_id_required")
    
    start_date = None
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        except ValueError:
            return _bad("invalid_date_format")
    
    try:
        assignment = svc.assign_user_to_position(user_id, position_id, start_date, notes)
        return _ok({
            "user_id": assignment.user_id,
            "position_id": assignment.position_id,
            "start_date": assignment.start_date.isoformat(),
            "notes": assignment.notes
        }, 201)
    except ValueError as e:
        return _bad(str(e), 409)

@api_positions_bp.post("/<int:position_id>/transfer")
@api_auth_required
@api_app_required("itcj", perms=["core.positions.api.assign_users"])
def transfer_position(position_id):
    """Transfiere un puesto de un usuario a otro"""
    payload = request.get_json(silent=True) or {}
    old_user_id = payload.get("old_user_id")
    new_user_id = payload.get("new_user_id")
    transfer_date_str = payload.get("transfer_date")
    
    if not new_user_id:
        return _bad("new_user_id_required")
    
    transfer_date = None
    if transfer_date_str:
        try:
            transfer_date = datetime.strptime(transfer_date_str, "%Y-%m-%d").date()
        except ValueError:
            return _bad("invalid_date_format")
    
    # Si no se especifica old_user_id, obtener el actual
    if not old_user_id:
        current_user_data = svc.get_position_current_user(position_id)
        if not current_user_data:
            return _bad("no_current_user")
        old_user_id = current_user_data["user_id"]
    
    try:
        success = svc.transfer_position(old_user_id, new_user_id, position_id, transfer_date)
        if success:
            return _ok({"transferred": True})
        return _bad("transfer_failed", 500)
    except Exception as e:
        return _bad(str(e), 500)

@api_positions_bp.delete("/<int:position_id>/remove-user")
@api_auth_required
@api_app_required("itcj", perms=["core.positions.api.unassign_users"])
def remove_user_from_position(position_id):
    """Remueve el usuario actual de un puesto"""
    payload = request.get_json(silent=True) or {}
    user_id = payload.get("user_id")
    end_date_str = payload.get("end_date")
    
    end_date = None
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            return _bad("invalid_date_format")
    
    # Si no se especifica user_id, obtener el actual
    if not user_id:
        current_user_data = svc.get_position_current_user(position_id)
        if not current_user_data:
            return _bad("no_current_user")
        user_id = current_user_data["user_id"]
    
    success = svc.remove_user_from_position(user_id, position_id, end_date)
    if success:
        return _ok({"removed": True})
    return _bad("removal_failed", 404)

# ---------------------------
# Permisos por Puesto
# ---------------------------

@api_positions_bp.get("/<int:position_id>/assignments")
@api_auth_required
@api_app_required("itcj", perms=["core.positions.api.read.assignments"])
def get_position_assignments(position_id):
    """Obtiene todas las asignaciones de un puesto por aplicación"""
    try:
        assignments = svc.get_position_assignments(position_id)
        return _ok(assignments)
    except ValueError as e:
        return _bad(str(e), 404)
    except Exception as e:
        current_app.logger.error(f"Error getting position assignments: {e}")
        return _bad("internal_server_error", 500)

@api_positions_bp.post("/<int:position_id>/apps/<string:app_key>/roles")
@api_auth_required
@api_app_required("itcj", perms=["core.authz.api.grant_roles"])
def assign_role_to_position(position_id, app_key):
    """Asigna un rol a un puesto en una aplicación"""
    payload = request.get_json(silent=True) or {}
    role_name = (payload.get("role_name") or "").strip()
    
    if not role_name:
        return _bad("role_name_required")
    
    try:
        created = svc.assign_role_to_position(position_id, app_key, role_name)
        return _ok({"created": created})
    except ValueError as e:
        return _bad(str(e), 400)

@api_positions_bp.delete("/<int:position_id>/apps/<string:app_key>/roles/<string:role_name>")
@api_auth_required
@api_app_required("itcj", perms=["core.authz.api.revoke_roles"])
def remove_role_from_position(position_id, app_key, role_name):
    """Remueve un rol de un puesto"""
    removed = svc.remove_role_from_position(position_id, app_key, role_name)
    return _ok({"removed": removed})

@api_positions_bp.post("/<int:position_id>/apps/<string:app_key>/perms")
@api_auth_required
@api_app_required("itcj", perms=["core.authz.api.grant_permissions"])
def assign_permission_to_position(position_id, app_key):
    """Asigna un permiso directo a un puesto"""
    payload = request.get_json(silent=True) or {}
    perm_code = (payload.get("code") or "").strip()
    allow = bool(payload.get("allow", True))
    
    if not perm_code:
        return _bad("code_required")
    
    try:
        created = svc.assign_permission_to_position(position_id, app_key, perm_code, allow)
        return _ok({"updated": created})
    except ValueError as e:
        return _bad(str(e), 400)

@api_positions_bp.delete("/<int:position_id>/apps/<string:app_key>/perms/<string:perm_code>")
@api_auth_required
@api_app_required("itcj", perms=["core.authz.api.revoke_permissions"])
def remove_permission_from_position(position_id, app_key, perm_code):
    """Remueve un permiso de un puesto"""
    # Para remover, asignar con allow=False y luego eliminar registro
    try:
        from itcj.core.services.authz_service import get_or_404_app, get_perm
        from itcj.core.models.position import PositionAppPerm
        
        app = get_or_404_app(app_key)
        perm = get_perm(app.id, perm_code)
        
        if not perm:
            return _bad("permission_not_found", 404)
        
        deleted = db.session.query(PositionAppPerm).filter_by(
            position_id=position_id,
            app_id=app.id,
            perm_id=perm.id
        ).delete()
        
        db.session.commit()
        return _ok({"removed": deleted > 0})
    except Exception as e:
        return _bad(str(e), 500)

# ---------------------------
# Consultas de Usuario
# ---------------------------

@api_positions_bp.get("/users/<int:user_id>/positions")
@api_auth_required
@api_app_required("itcj", perms=["core.positions.api.read.assignments"])
def get_user_positions(user_id):
    """Obtiene los puestos activos de un usuario"""
    positions = svc.get_user_active_positions(user_id)
    return _ok(positions)

@api_positions_bp.get("/users/<int:user_id>/apps/<string:app_key>/position-perms")
@api_auth_required
@api_app_required("itcj", perms=["core.authz.api.read.user_permissions"])
def get_user_position_permissions(user_id, app_key):
    """Obtiene los permisos efectivos de un usuario vía sus puestos"""
    try:
        perms = svc.get_position_effective_permissions(user_id, app_key)
        return _ok(sorted(list(perms)))
    except Exception as e:
        return _bad(str(e), 400)

# ---------------------------
# APIs para Gestión de Apps en Posiciones (nuevas)
# ---------------------------

@api_positions_bp.get("/<int:position_id>/apps/<string:app_key>/roles")
@api_auth_required
@api_app_required("itcj", perms=["core.authz.api.read.user_roles"])
def get_position_app_roles(position_id, app_key):
    """Obtiene los roles asignados a una posición en una app específica"""
    try:
        from itcj.core.services.authz_service import get_or_404_app
        from itcj.core.models.position import PositionAppRole
        from itcj.core.models.role import Role
        
        app = get_or_404_app(app_key)
        
        roles = (
            db.session.query(Role.name)
            .join(PositionAppRole, PositionAppRole.role_id == Role.id)
            .filter(
                PositionAppRole.position_id == position_id,
                PositionAppRole.app_id == app.id
            )
            .all()
        )
        
        return _ok([role[0] for role in roles])
    except Exception as e:
        return _bad(str(e), 400)

@api_positions_bp.get("/<int:position_id>/apps/<string:app_key>/perms")
@api_auth_required
@api_app_required("itcj", perms=["core.authz.api.read.user_permissions"])
def get_position_app_perms(position_id, app_key):
    """Obtiene los permisos directos asignados a una posición en una app específica"""
    try:
        from itcj.core.services.authz_service import get_or_404_app
        from itcj.core.models.position import PositionAppPerm
        from itcj.core.models.permission import Permission
        
        app = get_or_404_app(app_key)
        
        perms = (
            db.session.query(Permission.code)
            .join(PositionAppPerm, PositionAppPerm.perm_id == Permission.id)
            .filter(
                PositionAppPerm.position_id == position_id,
                PositionAppPerm.app_id == app.id,
                PositionAppPerm.allow == True
            )
            .all()
        )
        
        return _ok([perm[0] for perm in perms])
    except Exception as e:
        return _bad(str(e), 400)

@api_positions_bp.get("/<int:position_id>/effective-perms/<string:app_key>")
@api_auth_required
@api_app_required("itcj", perms=["core.authz.api.read.user_permissions"])
def get_position_effective_perms(position_id, app_key):
    """Obtiene los permisos efectivos de una posición en una app (roles + permisos directos)"""
    try:
        from itcj.core.services.authz_service import get_or_404_app
        from itcj.core.models.position import PositionAppRole, PositionAppPerm
        from itcj.core.models.role import Role
        from itcj.core.models.permission import Permission
        from itcj.core.models.role_permission import RolePermission
        
        app = get_or_404_app(app_key)
        
        # Permisos via roles
        perms_via_roles = (
            db.session.query(Permission.code)
            .join(RolePermission, RolePermission.perm_id == Permission.id)
            .join(PositionAppRole, PositionAppRole.role_id == RolePermission.role_id)
            .filter(
                PositionAppRole.position_id == position_id,
                PositionAppRole.app_id == app.id,
                Permission.app_id == app.id
            )
            .all()
        )
        
        # Permisos directos
        direct_perms = (
            db.session.query(Permission.code)
            .join(PositionAppPerm, PositionAppPerm.perm_id == Permission.id)
            .filter(
                PositionAppPerm.position_id == position_id,
                PositionAppPerm.app_id == app.id,
                PositionAppPerm.allow == True,
                Permission.app_id == app.id
            )
            .all()
        )
        
        all_perms = set()
        all_perms.update(p[0] for p in perms_via_roles)
        all_perms.update(p[0] for p in direct_perms)
        
        return _ok(sorted(list(all_perms)))
    except Exception as e:
        return _bad(str(e), 400)