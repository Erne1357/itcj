"""Invitaciones (vista de la secretaría): QR, búsqueda, envío y resumen del día.

Rutas bajo ``/api/prorrogas/v2/invitaciones``; los ``ServiceError`` salen con el
``{"error", "message", ...}`` en la raíz del JSON.
"""
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from itcj2.apps.prorrogas_tec.api._common import service_error_response as _err
from itcj2.apps.prorrogas_tec.services import invitation_service as svc
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["prorrogas_tec-invitaciones"])

_CREATE = ["prorrogas_tec.invitations.api.create"]


class InvitationIn(BaseModel):
    control_number: str
    correo: Optional[str] = None
    nombres: Optional[str] = None
    apellido_paterno: Optional[str] = None
    apellido_materno: Optional[str] = None
    program_id: Optional[int] = None


@router.post("/qr", name="prorrogas_tec.api.invitaciones.qr")
def issue_qr(user: dict = require_perms("prorrogas_tec", _CREATE)):
    return svc.issue_qr(int(user["sub"]))


@router.get("/alumno", name="prorrogas_tec.api.invitaciones.alumno")
def lookup(db: DbSession, control: str = Query(...), user: dict = require_perms("prorrogas_tec", _CREATE)):
    try:
        return svc.lookup(db, control)
    except ServiceError as e:
        return _err(e)


@router.post("", status_code=201, name="prorrogas_tec.api.invitaciones.create")
def create(body: InvitationIn, db: DbSession, user: dict = require_perms("prorrogas_tec", _CREATE)):
    try:
        inv, _token, enviado = svc.invite(
            db, raw_control=body.control_number, email=body.correo, actor_id=int(user["sub"]),
            nombres=body.nombres, apellido_paterno=body.apellido_paterno,
            apellido_materno=body.apellido_materno, program_id=body.program_id)
    except ServiceError as e:
        db.rollback()
        return _err(e)
    # `enviado` False: quedó registrada, pero el buzón no está conectado o Graph falló.
    return {"id": inv.id, "correo": inv.email, "expira": inv.expires_at.isoformat(), "enviado": enviado}


@router.get("/hoy", name="prorrogas_tec.api.invitaciones.hoy")
def today(db: DbSession, user: dict = require_perms("prorrogas_tec", _CREATE)):
    return svc.today_summary(db)
