"""API del estudiante: ver su estado, solicitar, cancelar y bajar sus PDF.

Rutas bajo ``/api/prorrogas/v2/estudiante``; los ``ServiceError`` salen con el
``{"error", "message", ...}`` en la raíz del JSON.
"""
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel

from itcj2.apps.prorrogas_tec.api._common import error_response, service_error_response as _err
from itcj2.apps.prorrogas_tec.models.document import ProrrogaDocument
from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
from itcj2.apps.prorrogas_tec.services.document_service import DocumentService
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.identity import folio
from itcj2.apps.prorrogas_tec.services.periods import period_label
from itcj2.apps.prorrogas_tec.services.request_service import RequestService
from itcj2.apps.prorrogas_tec.services.signature import parse_signature
from itcj2.core.models.student_profile import StudentProfile
from itcj2.core.models.user import User
from itcj2.core.utils.client_ip import client_ip
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["prorrogas_tec-estudiante"])

_READ = ["prorrogas_tec.requests.api.read.own"]
_CREATE = ["prorrogas_tec.requests.api.create.own"]
_CANCEL = ["prorrogas_tec.requests.api.cancel.own"]


class SolicitudIn(BaseModel):
    plazos: Any
    motivo: str
    program_id: int
    firma: str


@router.get("/estado", name="prorrogas_tec.api.estudiante.estado")
def estado(db: DbSession, user: dict = require_perms("prorrogas_tec", _READ)):
    uid = int(user["sub"])
    period, code = RequestService.access(db, uid)
    perfil = db.get(StudentProfile, uid)
    return {
        "puede_solicitar": code is None, "motivo": code,
        "semestre": period_label(period) if period else None,
        "program_id": perfil.program_id if perfil else None,
        "solicitudes": [RequestService.request_out(db, r) for r in RequestService.mine(db, uid)],
    }


@router.post("/solicitudes", status_code=201, name="prorrogas_tec.api.estudiante.crear")
def crear(body: SolicitudIn, request: Request, db: DbSession,
          user: dict = require_perms("prorrogas_tec", _CREATE)):
    student = db.get(User, int(user["sub"]))
    try:
        firma = parse_signature(body.firma)
        req = RequestService.create(
            db, student, plazos=body.plazos, motivo=body.motivo, program_id=body.program_id, firma=firma,
            ip=client_ip(request), user_agent=request.headers.get("user-agent"))
    except ServiceError as e:
        db.rollback()
        return _err(e)
    return {"id": req.id, "folio": folio(req.id)}


@router.post("/solicitudes/{request_id}/cancelar", name="prorrogas_tec.api.estudiante.cancelar")
def cancelar(request_id: int, db: DbSession, user: dict = require_perms("prorrogas_tec", _CANCEL)):
    try:
        req = RequestService.cancel(db, request_id, int(user["sub"]))
    except ServiceError as e:
        db.rollback()
        return _err(e)
    return RequestService.request_out(db, req)


@router.get("/solicitudes/{request_id}/documentos/{doc_id}.pdf", name="prorrogas_tec.api.estudiante.pdf")
def pdf(request_id: int, doc_id: int, db: DbSession, user: dict = require_perms("prorrogas_tec", _READ)):
    doc = (db.query(ProrrogaDocument)
           .join(ProrrogaRequest, ProrrogaRequest.id == ProrrogaDocument.request_id)
           .filter(ProrrogaDocument.id == doc_id, ProrrogaDocument.request_id == request_id,
                   ProrrogaRequest.student_id == int(user["sub"])).first())
    if doc is None:
        return error_response(404, "no_encontrada", "No se encontró el documento.")
    return Response(DocumentService.read_pdf(doc), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{folio(request_id)}-{doc.doc_type}.pdf"'})
