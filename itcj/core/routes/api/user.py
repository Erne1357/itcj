# itcj/core/routes/api/users.py
from flask import Blueprint, jsonify, request, g,current_app
from functools import wraps
from itcj.core.models.user import User
from itcj.core.utils.decorators import api_auth_required
from itcj.core.utils.security import verify_nip, hash_nip
from itcj.core.models import db
import logging

api_user_bp = Blueprint("api_user_bp", __name__)

DEFAULT_PASSWORD = "1234" # Cambia esto a DEFAULT_NIP si es lo que usas
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