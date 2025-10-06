# itcj/core/routes/api/departments.py
from flask import Blueprint, request, jsonify
from itcj.core.utils.decorators import api_auth_required, api_role_required
from itcj.core.services import departments_service as dept_svc

api_departments_bp = Blueprint("api_departments_bp", __name__)

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
    
    return jsonify({
        "status": "ok",
        "data": {
            **dept.to_dict(),
            'positions': dept_svc.get_department_positions(dept_id)
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
    
    if not code or not name:
        return jsonify({"status": "error", "error": "code_and_name_required"}), 400
    
    try:
        dept = dept_svc.create_department(code, name, description)
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
            if k in ['name', 'description', 'is_active']
        })
        return jsonify({"status": "ok", "data": dept.to_dict()})
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 404