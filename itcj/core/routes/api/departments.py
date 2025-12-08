# itcj/core/routes/api/departments.py
from flask import Blueprint, request, jsonify
from itcj.core.utils.decorators import api_auth_required, api_role_required, api_app_required
from itcj.core.services import departments_service as dept_svc

api_departments_bp = Blueprint("api_departments_bp", __name__)

@api_departments_bp.get("/direction")
@api_auth_required
@api_app_required("itcj", perms=["core.departments.api.read.hierarchy"])
def get_direction():
    """Obtiene la dirección (departamento raíz sin padre)"""
    direction = dept_svc.get_direction()
    return jsonify({
        "status": "ok", 
        "data": direction.to_dict(include_children=True) if direction else None
    })

@api_departments_bp.get("/subdirections")
@api_auth_required
@api_app_required("itcj", perms=["core.departments.api.read.hierarchy"])
def list_subdirections():
    """Lista solo las subdirecciones (departamentos padres)"""
    subdirs = dept_svc.list_subdirections()
    return jsonify({
        "status": "ok",
        "data": [d.to_dict(include_children=True) for d in subdirs]
    })

@api_departments_bp.get("/parent-options")
@api_auth_required
@api_app_required("itcj", perms=["core.departments.api.read"])
def list_parent_options():
    """Lista departamentos que pueden ser padres (dirección y subdirecciones)"""
    options = dept_svc.list_parent_options()
    return jsonify({
        "status": "ok",
        "data": [d.to_dict() for d in options]
    })

@api_departments_bp.get("/by-parent")
@api_auth_required
@api_app_required("itcj", perms=["core.departments.api.read"])
def list_by_parent():
    """Lista departamentos filtrados por parent_id"""
    parent_id = request.args.get('parent_id', type=int)
    depts = dept_svc.list_departments_by_parent(parent_id)
    return jsonify({
        "status": "ok",
        "data": [d.to_dict() for d in depts]
    })

@api_departments_bp.get("")
@api_auth_required
@api_app_required("itcj", perms=["core.departments.api.read"])
def list_departments():
    """Lista todos los departamentos"""
    depts = dept_svc.list_departments()
    return jsonify({
        "status": "ok",
        "data": [d.to_dict() for d in depts]
    })

@api_departments_bp.get("/<int:dept_id>")
@api_auth_required
@api_app_required("itcj", perms=["core.departments.api.read"])
def get_department_detail(dept_id):
    """Obtiene detalle completo de un departamento"""
    dept = dept_svc.get_department(dept_id)
    if not dept:
        return jsonify({"status": "error", "error": "not_found"}), 404
    
    # Convertir posiciones a diccionarios serializables
    positions = dept_svc.get_department_positions(dept_id)
    positions_data = []
    
    for position in positions:
        from itcj.core.services import positions_service as pos_svc
        current_user = pos_svc.get_position_current_user(position.id)
        
        positions_data.append({
            "id": position.id,
            "code": position.code,
            "title": position.title,
            "description": position.description,
            "email": position.email,
            "department_id": position.department_id,
            "is_active": position.is_active,
            "allows_multiple": position.allows_multiple,
            "current_user": current_user
        })
    
    return jsonify({
        "status": "ok",
        "data": {
            **dept.to_dict(include_children=True),
            'positions': positions_data
        }
    })

@api_departments_bp.post("")
@api_auth_required
@api_app_required("itcj", perms=["core.departments.api.create"])
def create_department():
    """Crea un nuevo departamento"""
    payload = request.get_json() or {}
    code = (payload.get('code') or '').strip()
    name = (payload.get('name') or '').strip()
    description = (payload.get('description') or '').strip() or None
    parent_id = payload.get('parent_id')
    icon_class = (payload.get('icon_class') or '').strip() or None
    
    if not code or not name:
        return jsonify({"status": "error", "error": "code_and_name_required"}), 400
    
    try:
        dept = dept_svc.create_department(code, name, description, parent_id, icon_class)
        return jsonify({"status": "ok", "data": dept.to_dict()}), 201
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 409

@api_departments_bp.patch("/<int:dept_id>")
@api_auth_required
@api_app_required("itcj", perms=["core.departments.api.update"])
def update_department(dept_id):
    """Actualiza un departamento"""
    payload = request.get_json() or {}
    try:
        dept = dept_svc.update_department(dept_id, **{
            k: v for k, v in payload.items()
            if k in ['name', 'description', 'is_active', 'parent_id', 'icon_class']
        })
        return jsonify({"status": "ok", "data": dept.to_dict()})
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 404

@api_departments_bp.get("/<int:dept_id>/users")
@api_auth_required
@api_app_required("itcj", perms=["core.departments.api.read"])
def get_department_users(dept_id):
    """Obtiene todos los usuarios asignados a un departamento como jefes o personal"""
    try:
        # Verificar que el departamento existe
        dept = dept_svc.get_department(dept_id)
        if not dept:
            return jsonify({"status": "error", "error": "Department not found"}), 404
        
        # Obtener usuarios que tienen puestos en este departamento
        from itcj.core.models.position import Position, UserPosition
        from itcj.core.models.user import User
        from itcj.core.extensions import db
        
        # Query para obtener usuarios con puestos activos en el departamento
        users_data = (
            db.session.query(User, Position, UserPosition)
            .join(UserPosition, User.id == UserPosition.user_id)
            .join(Position, UserPosition.position_id == Position.id)
            .filter(
                Position.department_id == dept_id,
                Position.is_active == True,
                UserPosition.is_active == True,
                User.is_active == True
            )
            .distinct(User.id)
            .all()
        )
        
        # Formatear respuesta con estadísticas de tickets (si aplica)
        users_list = []
        seen_users = set()
        
        for user, position, assignment in users_data:
            if user.id in seen_users:
                continue
            seen_users.add(user.id)
            
            # Contar tickets del usuario (si existe la tabla de tickets de helpdesk)
            ticket_count = 0
            try:
                # Esto solo funcionará si helpdesk está disponible
                from itcj.apps.helpdesk.models.ticket import Ticket
                ticket_count = Ticket.query.filter_by(
                    requester_id=user.id,
                    requester_department_id=dept_id
                ).count()
            except (ImportError, AttributeError):
                # Si helpdesk no está disponible, continuar sin contar tickets
                pass
            
            users_list.append({
                "id": user.id,
                "name": user.full_name,
                "full_name": user.full_name,
                "email": user.email,
                "username": user.username,
                "control_number": user.control_number,
                "is_active": user.is_active,
                "role": user.role.name if user.role else None,
                "position": {
                    "id": position.id,
                    "code": position.code,
                    "title": position.title
                },
                "assignment": {
                    "start_date": assignment.start_date.isoformat() if assignment.start_date else None,
                    "notes": assignment.notes
                },
                "ticket_count": ticket_count
            })
        
        return jsonify({
            "status": "ok", 
            "data": {
                "department": dept.to_dict(),
                "users": users_list,
                "total": len(users_list)
            }
        })
        
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"Error getting department users: {e}")
        return jsonify({"status": "error", "error": "Internal server error"}), 500