# itcj/core/routes/api/users.py
from flask import Blueprint, jsonify, request, current_app,g
from itcj.core.models.user import User
from itcj.core.utils.decorators import api_auth_required, api_role_required, api_app_required
from itcj.core.services.authz_service import user_roles_in_app
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
@api_app_required("itcj", perms=["core.users.api.read"])
def list_users():
    """Lista todos los usuarios del sistema con filtros y paginación"""
    try:
        # Parámetros de búsqueda y filtros
        search = request.args.get("search", "").strip()
        role_filter = request.args.get("role")
        app_filter = request.args.get("app")
        status_filter = request.args.get("status")  # 'active' o 'inactive'
        only_staff = request.args.get("only_staff", "false").lower() == "true"
        
        # Parámetros de paginación
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(int(request.args.get("per_page", 20)), 100)
        
        # Construir consulta base
        query = db.session.query(User)
        
        # Filtro por estado
        if status_filter == "active":
            query = query.filter(User.is_active == True)
        elif status_filter == "inactive":
            query = query.filter(User.is_active == False)
        
        # Filtro por búsqueda en nombre, email, username o control_number
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                db.or_(
                    User.full_name.ilike(search_pattern),
                    User.email.ilike(search_pattern),
                    User.username.ilike(search_pattern),
                    User.control_number.ilike(search_pattern),
                )
            )
        
        # Filtro para incluir solo personal (excluir estudiantes)
        if only_staff:
            query = query.filter(User.control_number == None)

        # Filtro por rol
        if role_filter:
            from itcj.core.models.role import Role
            query = query.join(Role).filter(Role.name == role_filter)
        
        # TODO: Filtro por app (requiere consulta a las tablas de autorización)
        # Esto es más complejo, ya que necesitas revisar las tablas de autorización
        
        # Ordenar
        query = query.order_by(User.full_name)
        
        # Aplicar paginación
        pagination = query.paginate(
            page=page, 
            per_page=per_page, 
            error_out=False
        )
        
        # Formatear respuesta
        users_data = []
        for user in pagination.items:
            users_data.append({
                "id": user.id,
                "full_name": user.full_name,
                "email": user.email,
                "username": user.username,
                "control_number": user.control_number,
                "role": user.role.name if user.role else None,
                "roles": [role.name for role in user.roles] if hasattr(user, 'roles') else [],
                "is_active": user.is_active
            })
        
        return _ok({
            "users": users_data,
            "pagination": {
                "page": pagination.page,
                "per_page": pagination.per_page,
                "total": pagination.total,
                "pages": pagination.pages,
                "has_next": pagination.has_next,
                "has_prev": pagination.has_prev,
                "next_num": pagination.next_num,
                "prev_num": pagination.prev_num
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Error listing users: {e}")
        return _bad("internal_server_error", 500)

@api_users_bp.post("")
@api_auth_required
@api_app_required("itcj", perms=["core.users.api.create"])
def create_user():
    """Crea un nuevo usuario (estudiante o personal)"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid input"}), 400

    # Recibir nombres separados o full_name (retrocompatibilidad)
    first_name = data.get("first_name")
    last_name = data.get("last_name")
    middle_name = data.get("middle_name")
    full_name = data.get("full_name")  # Retrocompatibilidad
    
    email = data.get("email")
    user_type = data.get("user_type")
    password = data.get("password")

    # Si no vienen los nombres separados pero viene full_name, intentar separarlo
    if not (first_name and last_name) and full_name:
        name_parts = full_name.strip().split()
        if len(name_parts) < 2:
            return jsonify({"error": "Invalid name format"}), 400
        if len(name_parts) >= 3:
            first_name = ' '.join(name_parts[:-2]).upper()
            last_name = name_parts[-2].upper()
            middle_name = name_parts[-1].upper()
        else:
            first_name = name_parts[0].upper()
            last_name = name_parts[-1].upper()
            middle_name = None

    if not all([first_name, last_name, user_type, password]):
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
            first_name=first_name.upper(),
            last_name=last_name.upper(),
            middle_name=middle_name.upper() if middle_name else None,
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

@api_users_bp.get('/me/department')
@api_auth_required
def get_my_department():
    """Obtener departamento del usuario actual"""
    from itcj.core.services.departments_service import get_user_department

    user_id = int(g.current_user['sub'])
    department = get_user_department(user_id)

    if not department:
        return jsonify({
            'success': False,
            'error': 'Usuario no tiene departamento asignado'
        }), 404

    return jsonify({
        'success': True,
        'data': {
            'id': department.id,
            'name': department.name,
            'code': department.code
        }
    }), 200


@api_users_bp.get('/<int:target_user_id>/department')
@api_app_required('helpdesk')
def get_user_department_by_id(target_user_id):
    """
    Obtener departamento de un usuario específico
    (Solo para Centro de Cómputo - crear tickets por otros usuarios)
    """
    from itcj.core.services.departments_service import get_user_department
    from itcj.core.services.authz_service import user_roles_in_app, _get_users_with_position

    current_user_id = int(g.current_user['sub'])
    user_roles = user_roles_in_app(current_user_id, 'helpdesk')
    secretary_comp_center = _get_users_with_position(['secretary_comp_center'])

    # Solo Centro de Cómputo puede consultar departamentos de otros usuarios
    if 'admin' not in user_roles and current_user_id not in secretary_comp_center and 'tech_desarrollo' not in user_roles and 'tech_soporte' not in user_roles:
        return jsonify({
            'success': False,
            'error': 'No tiene permiso para consultar el departamento de otros usuarios'
        }), 403

    department = get_user_department(target_user_id)

    if not department:
        return jsonify({
            'success': False,
            'error': 'Usuario no tiene departamento asignado'
        }), 404

    return jsonify({
        'success': True,
        'data': {
            'id': department.id,
            'name': department.name,
            'code': department.code
        }
    }), 200

@api_users_bp.get('/by-app/<app_key>')
@api_app_required('helpdesk')  # Solo requiere acceso a helpdesk
def list_users_by_app(app_key):
    """
    Lista usuarios con acceso a una aplicación específica.
    Solo requiere tener acceso a la app helpdesk.

    Query params:
        - search: Término de búsqueda (prioriza username, luego nombre, email, control_number)
        - page: Número de página (default: 1)
        - per_page: Items por página (default: 20, max: 50)

    Returns:
        200: Lista de usuarios con acceso a la app
    """
    try:
        # Obtener app
        from itcj.core.models.app import App
        app = App.query.filter_by(key=app_key, is_active=True).first()
        if not app:
            return _bad("App no encontrada", 404)

        # Parámetros de búsqueda
        search = request.args.get("search", "").strip()
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(int(request.args.get("per_page", 20)), 50)

        # Obtener usuarios con acceso a la app (roles o permisos, directos o por puesto)
        from itcj.core.models.user_app_role import UserAppRole
        from itcj.core.models.user_app_perm import UserAppPerm
        from itcj.core.models.position import UserPosition, PositionAppRole, PositionAppPerm

        # 1. Usuarios con roles DIRECTOS en la app
        users_with_roles = db.session.query(User.id).join(
            UserAppRole, UserAppRole.user_id == User.id
        ).filter(
            UserAppRole.app_id == app.id,
            User.is_active == True
        )

        # 2. Usuarios con permisos DIRECTOS en la app
        users_with_perms = db.session.query(User.id).join(
            UserAppPerm, UserAppPerm.user_id == User.id
        ).filter(
            UserAppPerm.app_id == app.id,
            UserAppPerm.allow == True,
            User.is_active == True
        )

        # 3. Usuarios con roles a través de PUESTOS
        users_with_position_roles = db.session.query(User.id).join(
            UserPosition, UserPosition.user_id == User.id
        ).join(
            PositionAppRole, PositionAppRole.position_id == UserPosition.position_id
        ).filter(
            PositionAppRole.app_id == app.id,
            UserPosition.is_active == True,
            User.is_active == True
        )

        # 4. Usuarios con permisos a través de PUESTOS
        users_with_position_perms = db.session.query(User.id).join(
            UserPosition, UserPosition.user_id == User.id
        ).join(
            PositionAppPerm, PositionAppPerm.position_id == UserPosition.position_id
        ).filter(
            PositionAppPerm.app_id == app.id,
            PositionAppPerm.allow == True,
            UserPosition.is_active == True,
            User.is_active == True
        )

        # Unión de todos los casos
        user_ids_query = users_with_roles.union(
            users_with_perms
        ).union(
            users_with_position_roles
        ).union(
            users_with_position_perms
        )

        # Construir query principal
        query = db.session.query(User).filter(
            User.id.in_(user_ids_query),
            User.is_active == True
        )

        # Aplicar búsqueda si se proporciona (priorizar username)
        if search:
            search_pattern = f"%{search}%"
            # Priorizar username en el ordenamiento
            query = query.filter(
                db.or_(
                    User.username.ilike(search_pattern),
                    User.full_name.ilike(search_pattern),
                    User.email.ilike(search_pattern),
                    User.control_number.ilike(search_pattern)
                )
            ).order_by(
                # Ordenar poniendo primero los que coinciden en username
                db.case(
                    (User.username.ilike(search_pattern), 0),
                    else_=1
                ),
                User.full_name
            )
        else:
            query = query.order_by(User.full_name)

        # Aplicar paginación
        pagination = query.paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )

        # Formatear respuesta
        users_data = []
        for user in pagination.items:
            # Convertir roles a lista (user_roles_in_app retorna un set)
            user_roles = user_roles_in_app(user.id, 'helpdesk')
            roles_list = list(user_roles) if isinstance(user_roles, set) else user_roles
            
            users_data.append({
                "id": user.id,
                "full_name": user.full_name,
                "email": user.email,
                "username": user.username,
                "control_number": user.control_number,
                "roles": roles_list,
                "is_active": user.is_active
            })

        return _ok({
            "users": users_data,
            "pagination": {
                "page": pagination.page,
                "per_page": pagination.per_page,
                "total": pagination.total,
                "pages": pagination.pages,
                "has_next": pagination.has_next,
                "has_prev": pagination.has_prev,
                "next_num": pagination.next_num,
                "prev_num": pagination.prev_num
            }
        })

    except Exception as e:
        current_app.logger.error(f"Error listing users by app: {e}")
        return _bad("internal_server_error", 500)