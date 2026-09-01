"""
Requests API — Solicitudes de plazos de pago.
Fuente: itcj/apps/prorrogas_tec/api/requests.py
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from itcj2.apps.prorrogas_tec.helpers import require_admission_open
from itcj2.apps.prorrogas_tec.models.request import Request_pro
from itcj2.apps.prorrogas_tec.services.request_service import get_request_pro_service
from itcj2.dependencies import DbSession, require_roles, CurrentUser
from itcj2.core.models.user import User

router = APIRouter(tags=["prorrogas_tec-requests"])
logger = logging.getLogger(__name__)


class CreatePaymentPlanBody(BaseModel):
    program_id: int
    payments_terms: int
    letter: str


def _get_student(user: dict, db: DbSession) -> User:
    """Obtiene el objeto User del estudiante autenticado."""
    uid = int(user["sub"])
    return db.get(User, uid)


def _to_http_exception(result) -> HTTPException:
    detail = {"error": result.error}
    if result.message:
        detail["message"] = result.message
    if result.data:
        detail.update(result.data)
    return HTTPException(status_code=result.status_code, detail=detail)


# ==================== GET /mine ====================
@router.get("/mine")
def my_requests(
    user: dict = require_roles("prorrogas_tec", ["student"]),
    db: DbSession = None,
):
    student = _get_student(user, db)
    service = get_request_pro_service()
    return service.get_student_requests(db, student)


# ==================== POST / ====================
@router.post("", status_code=201)
def create_request(
    body: CreatePaymentPlanBody,
    user: dict = require_roles("prorrogas_tec", ["student"]),
    db: DbSession = None,
):
    """Crea una nueva solicitud de plazos de pago."""
    require_admission_open()

    student = _get_student(user, db)
    service = get_request_pro_service()
    result = service.create_payment_plan_request(
        db,
        student=student,
        program_id=body.program_id,
        payments_terms=body.payments_terms,
        letter=body.letter,
    )

    if result.success:
        response_data = {"ok": True}
        if result.data:
            response_data.update(result.data)
        return response_data
    raise _to_http_exception(result)


# ==================== PATCH /<req_id>/cancel ====================
@router.patch("/{req_id}/cancel")
def cancel_request(
    req_id: int,
    user: dict = require_roles("prorrogas_tec", ["student"]),
    db: DbSession = None,
):
    require_admission_open()
    student = _get_student(user, db)
    request_obj = (
        db.query(Request_pro)
        .filter(Request_pro.id == req_id, Request_pro.student_id == student.id)
        .first()
    )
    if not request_obj:
        raise HTTPException(status_code=404, detail="request_not_found")

    service = get_request_pro_service()
    result = service.cancel_request(db, request_obj, student)

    if result.success:
        return {"ok": True}
    raise _to_http_exception(result)