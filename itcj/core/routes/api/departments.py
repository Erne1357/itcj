# itcj/core/routes/api/departments.py
from flask import Blueprint, request, jsonify
from itcj.core.utils.decorators import api_auth_required, api_role_required
from itcj.core.services import departments_service as dept_svc

api_departments_bp = Blueprint("api_departments_bp", __name__)

@api_departments_bp.get("/subdirections")
@api_auth_required
@api_role_required(["admin"])
def list_subdirections():
    """Lista solo las subdirecciones (departamentos padres)"""
    subdirs = dept_svc.list_subdirections()
    return jsonify({
        "status": "ok",
        "data": [d.to_dict(include_children=True) for d in subdirs]
    })

@api_departments_bp.get("/by-parent")
@api_auth_required
@api_role_required(["admin"])
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
@api_role_required(["admin"])
def list_departments():
    """Lista todos los departamentos"""
    depts = dept_svc.list_departments()
    return jsonify({
        "status": "ok",
        "data": [d.to_dict() for d in depts]
    })

@api_departments_bp.get("/<int:dept_id>")
@api_auth_required
@api_role_required(["admin"])
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
@api_role_required(["admin"])
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
@api_role_required(["admin"])
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