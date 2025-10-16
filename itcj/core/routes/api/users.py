# itcj/core/routes/api/users.py
from flask import Blueprint, jsonify, request, current_app
from itcj.core.models.user import User
from itcj.core.utils.decorators import api_auth_required, api_role_required
from itcj.core.extensions import db
from sqlalchemy.exc import IntegrityError
from itcj.core.utils.security import hash_nip
from itcj.core.models.role import Role


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

@api_users_bp.post("")
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