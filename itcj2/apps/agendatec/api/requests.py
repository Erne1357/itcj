"""
Requests API v2 — Solicitudes de estudiantes.
Fuente: itcj/apps/agendatec/routes/api/requests.py
"""
import logging

from fastapi import APIRouter, HTTPException

from itcj2.apps.agendatec.helpers import require_admission_open
from itcj2.apps.agendatec.schemas.requests import CreateRequestBody
from itcj2.dependencies import DbSession, require_roles, CurrentUser

from itcj2.apps.agendatec.models.request import Request as AgendaRequest
from itcj2.apps.agendatec.services import get_request_service
from itcj2.core.models.user import User

router = APIRouter(tags=["agendatec-requests"])
logger = logging.getLogger(__name__)


def _get_student(user: dict, db: DbSession) -> User:
    """Obtiene el objeto User del estudiante autenticado."""
    uid = int(user["sub"])
    return db.query(User).get(uid)


# ==================== GET /mine ====================

@router.get("/mine")
def my_requests(
    user: dict = require_roles("agendatec", ["student"]),
    db: DbSession = None,
):
    """
    Obtiene las solicitudes del estudiante autenticado.

    Returns:
        JSON con active_period, active (solicitud activa),
        history (historial) y periods (períodos referenciados).
    """
    student = _get_student(user, db)
    service = get_request_service()
    return service.get_student_requests(db, student)


# ==================== POST / ====================

@router.post("", status_code=201)
def create_request(
    body: CreateRequestBody,
    user: dict = require_roles("agendatec", ["student"]),
    db: DbSession = None,
):
    """
    Crea una nueva solicitud (DROP o APPOINTMENT).
    Valida que la ventana de admisión esté abierta (@api_closed).
    """
    require_admission_open()

    student = _get_student(user, db)
    service = get_request_service()

    if body.type == "DROP":
        result = service.create_drop_request(
            db,
            student=student,
            program_id=body.program_id,
            description=body.description,
        )
    else:  # APPOINTMENT
        if not body.slot_id:
            raise HTTPException(status_code=400, detail="slot_id_required")
        result = service.create_appointment_request(
            db,
            student=student,
            program_id=body.program_id,
            slot_id=body.slot_id,
            description=body.description,
        )

    if result.success:
        response_data = {"ok": True}
        if result.data:
            response_data.update(result.data)
        return response_data
    else:
        detail = {"error": result.error}
        if result.message:
            detail["message"] = result.message
        if result.data:
            detail.update(result.data)
        raise HTTPException(status_code=result.status_code, detail=detail)


# ==================== PATCH /<req_id>/cancel ====================

@router.patch("/{req_id}/cancel")
def cancel_request(
    req_id: int,
    user: dict = require_roles("agendatec", ["student"]),
    db: DbSession = None,
):
    """
    Cancela una solicitud del estudiante.
    Valida que la ventana de admisión esté abierta (@api_closed).
    """
    require_admission_open()

    student = _get_student(user, db)

    request_obj = (
        db.query(AgendaRequest)
        .filter(AgendaRequest.id == req_id, AgendaRequest.student_id == student.id)
        .first()
    )
    if not request_obj:
        raise HTTPException(status_code=404, detail="request_not_found")

    service = get_request_service()
    result = service.cancel_request(db, request_obj, student)

    if result.success:
        return {"ok": True}
    else:
        detail = {"error": result.error}
        if result.message:
            detail["message"] = result.message
        raise HTTPException(status_code=result.status_code, detail=detail)
