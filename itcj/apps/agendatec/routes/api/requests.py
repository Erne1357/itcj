# routes/api/requests.py
"""
API de solicitudes para AgendaTec.

Este módulo contiene los endpoints para gestión de solicitudes de estudiantes:
- Consulta de solicitudes propias
- Creación de solicitudes (citas y bajas)
- Cancelación de solicitudes

La lógica de negocio está delegada al RequestService.
"""
from flask import Blueprint, g, jsonify, request

from itcj.apps.agendatec.models import db
from itcj.apps.agendatec.models.request import Request
from itcj.apps.agendatec.services import get_request_service
from itcj.core.models.user import User
from itcj.core.utils.decorators import api_app_required, api_auth_required, api_closed

api_req_bp = Blueprint("api_requests", __name__)


def _get_current_student() -> User:
    """
    Obtiene el objeto User del estudiante autenticado.

    Returns:
        Instancia del modelo User correspondiente al token JWT actual.
    """
    uid = g.current_user["sub"]
    return db.session.query(User).get(uid)


@api_req_bp.get("/mine")
@api_auth_required
@api_app_required(app_key="agendatec", roles=["student"])
def my_requests():
    """
    Obtiene las solicitudes del estudiante autenticado.
    
    Returns:
        JSON con active_period, active (solicitud activa), 
        history (historial) y periods (períodos referenciados).
    """
    student = _get_current_student()
    service = get_request_service()
    result = service.get_student_requests(student)
    return jsonify(result)


@api_req_bp.post("")
@api_closed
@api_auth_required
@api_app_required(app_key="agendatec", roles=["student"])
def create_request():
    """
    Crea una nueva solicitud (DROP o APPOINTMENT).
    
    Request Body:
        - type: "DROP" o "APPOINTMENT"
        - program_id: ID del programa
        - slot_id: ID del slot (solo para APPOINTMENT)
        - description: Descripción opcional
        
    Returns:
        JSON con request_id (y appointment_id para citas).
    """
    student = _get_current_student()
    data = request.get_json(silent=True) or {}
    req_type = (data.get("type") or "").upper()
    service = get_request_service()

    if req_type == "DROP":
        result = service.create_drop_request(
            student=student,
            program_id=int(data.get("program_id")),
            description=data.get("description"),
        )
    elif req_type == "APPOINTMENT":
        try:
            program_id = int(data.get("program_id"))
            slot_id = int(data.get("slot_id"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid_payload"}), 400

        result = service.create_appointment_request(
            student=student,
            program_id=program_id,
            slot_id=slot_id,
            description=data.get("description"),
        )
    else:
        return jsonify({"error": "invalid_type"}), 400

    # Retornar resultado del servicio
    if result.success:
        response_data = {"ok": True}
        if result.data:
            response_data.update(result.data)
        return jsonify(response_data), result.status_code
    else:
        response_data = {"error": result.error}
        if result.message:
            response_data["message"] = result.message
        if result.data:
            response_data.update(result.data)
        return jsonify(response_data), result.status_code


@api_req_bp.patch("/<int:req_id>/cancel")
@api_closed
@api_auth_required
@api_app_required(app_key="agendatec", roles=["student"])
def cancel_request(req_id: int):
    """
    Cancela una solicitud del estudiante.
    
    Args:
        req_id: ID de la solicitud a cancelar.
        
    Returns:
        JSON con ok=True si fue exitoso.
    """
    student = _get_current_student()
    
    # Buscar la solicitud del estudiante
    request_obj = (
        db.session.query(Request)
        .filter(Request.id == req_id, Request.student_id == student.id)
        .first()
    )

    if not request_obj:
        return jsonify({"error": "request_not_found"}), 404

    service = get_request_service()
    result = service.cancel_request(request_obj, student)

    if result.success:
        return jsonify({"ok": True}), result.status_code
    else:
        response_data = {"error": result.error}
        if result.message:
            response_data["message"] = result.message
        return jsonify(response_data), result.status_code
