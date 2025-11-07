# itcj/core/routes/api/users.py
from flask import Blueprint, jsonify, request, g,current_app
from functools import wraps
from itcj.core.models.user import User
from itcj.core.utils.decorators import api_auth_required
from itcj.core.utils.security import verify_nip, hash_nip
from itcj.core.services.authz_service import user_roles_in_app
from itcj.core.models.app import App
from itcj.core.models import db
import logging

api_user_bp = Blueprint("api_user_bp", __name__)

DEFAULT_PASSWORD = "1234"  
def _current_user():
    try:
        uid = int(g.current_user["sub"])
    except Exception:
        return None
    u = db.session.query(User).get(uid)
    return u
# Endpoint para verificar si el usuario debe cambiar su contraseña
@api_user_bp.get("/password-state")
@api_auth_required
def user_password_state():
    u = _current_user()
    if not u:
        return jsonify({"error": "user_not_found"}), 404
    # Solo aplica para usuarios no estudiantes
    if u.role.name == "student":
        return jsonify({"must_change": False})
    # Verifica si la contraseña del usuario es la por defecto
    must_change = verify_nip(DEFAULT_PASSWORD, u.nip_hash)
    return jsonify({"must_change": must_change})

# Endpoint para cambiar la contraseña del usuario
@api_user_bp.post("/change-password")
@api_auth_required
def change_password():
    u = _current_user()
    if not u or u.role.name == "student":
        return jsonify({"error": "unauthorized"}), 403
    
    try:
        new_password = request.json.get("new_password")
        if not new_password or not new_password.isdigit() or len(new_password) != 4:
            return jsonify({"error": "invalid_password"}), 400
        
        user = User.query.filter_by(id=u.id).first()
        if not user:
            return jsonify({"error": "user_not_found"}), 404
        
        # Hashea y guarda la nueva contraseña
        user.nip_hash = hash_nip(new_password)
        user.must_change_password = False
        db.session.commit() 
        
        return jsonify({"message": "password_updated"}), 200
        
    except Exception as e:
        current_app.logger.error(f"Error changing password: {e}")
        return jsonify({"error": "internal_server_error"}), 500
    

@api_user_bp.get("/me")
@api_auth_required
def get_current_user():
    """Obtiene información del usuario actual"""
    u = _current_user()
    if not u:
        return jsonify({"error": "user_not_found"}), 404
    
    # Obtener rol global (puedes ajustar según tu lógica)
    global_role = u.role.name if hasattr(u, 'role') and u.role else "Usuario"
    
    apps_keys = App.query.with_entities(App.key).all()
    apps_keys = [app.key for app in apps_keys]

    roles = {}
    for app_key in apps_keys:
        app_roles = user_roles_in_app(u.id, app_key)
        # Convertir set a lista para serialización JSON
        roles[app_key] = list(app_roles) if isinstance(app_roles, set) else app_roles
    

    # Obtener posiciones activas del usuario (si aplica)
    positions = []
    if hasattr(u, 'position_assignments'):
        from itcj.core.models.position import UserPosition
        active_positions = UserPosition.query.filter_by(
            user_id=u.id,
            is_active=True
        ).all()
        positions = [
            {
                'title': p.position.title,
                'department': p.position.department.name if p.position.department else None
            }
            for p in active_positions
        ]
    
    return jsonify({
        "status": "ok",
        "data": {
            "id": u.id,
            "username": u.username,
            "full_name": u.full_name,
            "email": u.email,
            "role": global_role,
            "roles" : roles,
            "positions": positions
        }
    })

@api_user_bp.get("/me/profile")
@api_auth_required
def get_full_profile():
    """Obtiene el perfil completo del usuario actual"""
    from itcj.core.services.profile_service import get_user_profile_data
    
    user_id = int(g.current_user["sub"])
    profile = get_user_profile_data(user_id)
    
    if not profile:
        return jsonify({"error": "user_not_found"}), 404
    
    return jsonify({
        "status": "ok",
        "data": profile
    })

@api_user_bp.get("/me/activity")
@api_auth_required
def get_my_activity():
    """Obtiene la actividad reciente del usuario"""
    from itcj.core.services.profile_service import get_user_activity
    
    user_id = int(g.current_user["sub"])
    limit = request.args.get('limit', 10, type=int)
    
    activities = get_user_activity(user_id, limit=min(limit, 50))
    
    return jsonify({
        "status": "ok",
        "data": activities
    })

@api_user_bp.get("/me/notifications")
@api_auth_required
def get_my_notifications():
    """Obtiene las notificaciones del usuario"""
    from itcj.core.services.profile_service import get_user_notifications
    
    user_id = int(g.current_user["sub"])
    unread_only = request.args.get('unread_only', 'false').lower() == 'true'
    limit = request.args.get('limit', 20, type=int)
    
    notifications = get_user_notifications(user_id, unread_only, min(limit, 100))
    
    return jsonify({
        "status": "ok",
        "data": notifications
    })

@api_user_bp.patch("/me/profile")
@api_auth_required
def update_my_profile():
    """Actualiza información básica del perfil"""
    user_id = int(g.current_user["sub"])
    user = User.query.get(user_id)
    
    if not user:
        return jsonify({"error": "user_not_found"}), 404
    
    data = request.get_json()
    
    # Solo permitir actualizar campos no críticos
    allowed_fields = ['email']
    
    for field in allowed_fields:
        if field in data:
            setattr(user, field, data[field])
    
    try:
        db.session.commit()
        return jsonify({"status": "ok", "message": "profile_updated"})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating profile: {e}")
        return jsonify({"error": "update_failed"}), 500