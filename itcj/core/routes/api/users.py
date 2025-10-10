# itcj/core/routes/api/users.py
from flask import Blueprint, jsonify, request, current_app
from itcj.core.models.user import User
from itcj.core.utils.decorators import api_auth_required, api_role_required
from itcj.core.extensions import db

api_users_bp = Blueprint("api_users_bp", __name__)

def _ok(data=None, status=200):
    return (jsonify({"status": "ok", "data": data}) if data is not None else ("", 204)), status

def _bad(msg="bad_request", status=400):
    return jsonify({"status": "error", "error": msg}), status

# Endpoint para listar usuarios (para asignación a puestos)
@api_users_bp.get("")
@api_auth_required
@api_role_required(["admin"])
def list_users():
    """Lista todos los usuarios del sistema (para asignación a puestos)"""
    try:
        # Obtener parámetros de filtro opcionales
        search = request.args.get("search", "").strip()
        role_filter = request.args.get("role")
        limit = min(int(request.args.get("limit", 50)), 100)  # Máximo 100 usuarios
        
        # Construir consulta
        query = db.session.query(User).filter(User.is_active == True)
        
        # Filtro por búsqueda en nombre o email
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                db.or_(
                    User.full_name.ilike(search_pattern),
                    User.email.ilike(search_pattern)
                )
            )
        
        # Filtro por rol (si se especifica)
        if role_filter:
            from itcj.core.models.role import Role
            query = query.join(Role).filter(Role.name == role_filter)
        
        # Ordenar y limitar
        users = query.order_by(User.full_name).limit(limit).all()
        
        # Formatear respuesta
        users_data = []
        for user in users:
            users_data.append({
                "id": user.id,
                "name": user.full_name,
                "full_name": user.full_name,
                "email": user.email,
                "username": user.username,
                "control_number": user.control_number,
                "role": user.role.name if user.role else None,
                "is_active": user.is_active
            })
        
        return _ok(users_data)
        
    except Exception as e:
        current_app.logger.error(f"Error listing users: {e}")
        return _bad("internal_server_error", 500)
