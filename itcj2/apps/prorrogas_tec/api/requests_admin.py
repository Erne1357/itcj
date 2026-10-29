"""API de la secretaria: solicitudes pendientes, ver sus PDF y decidir.

Rutas bajo ``/api/prorrogas/v2/solicitudes``.
"""
from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from itcj2.apps.prorrogas_tec.api._common import error_response, service_error_response as _err
from itcj2.apps.prorrogas_tec.models.document import ProrrogaDocument
from itcj2.apps.prorrogas_tec.models.request import ProrrogaRequest
from itcj2.apps.prorrogas_tec.services.document_service import DocumentService
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.identity import folio
from itcj2.apps.prorrogas_tec.services.request_service import RequestService
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["prorrogas_tec-solicitudes"])

_READ = ["prorrogas_tec.requests.api.read.all"]
_DECIDE = ["prorrogas_tec.requests.api.decide"]


class DecisionIn(BaseModel):
    aceptar: bool
    comentario: str | None = None


@router.get("", name="prorrogas_tec.api.solicitudes.pendientes")
def pendientes(db: DbSession, user: dict = require_perms("prorrogas_tec", _READ)):
    items = []
    for r in RequestService.pending(db):
        formato = next((d for d in DocumentService.current(db, r) if d.doc_type == "formato_solicitud"), None)
        items.append({
            "id": r.id, "folio": folio(r.id), "nombre": r.student_name, "control": r.control_number,
            "correo": r.email, "recibida": r.created_at.isoformat(), "plazos": r.requested_terms,
            "documento_id": formato.id if formato else None})
    return {"items": items}


@router.get("/{request_id}", name="prorrogas_tec.api.solicitudes.ver")
def ver(request_id: int, db: DbSession, user: dict = require_perms("prorrogas_tec", _READ)):
    req = db.get(ProrrogaRequest, request_id)
    if req is None:
        return error_response(404, "no_encontrada", "No se encontró la solicitud.")
    return RequestService.request_out(db, req)


@router.get("/{request_id}/documentos/{doc_id}.pdf", name="prorrogas_tec.api.solicitudes.pdf")
def pdf(request_id: int, doc_id: int, db: DbSession, user: dict = require_perms("prorrogas_tec", _READ)):
    doc = db.query(ProrrogaDocument).filter_by(id=doc_id, request_id=request_id).first()
    if doc is None:
        return error_response(404, "no_encontrada", "No se encontró el documento.")
    return Response(DocumentService.read_pdf(doc), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{folio(request_id)}-{doc.doc_type}.pdf"'})


@router.post("/{request_id}/decision", name="prorrogas_tec.api.solicitudes.decidir")
def decidir(request_id: int, body: DecisionIn, db: DbSession,
            user: dict = require_perms("prorrogas_tec", _DECIDE)):
    try:
        req = RequestService.decide(db, request_id, int(user["sub"]), aceptar=body.aceptar,
                                    comentario=body.comentario)
    except ServiceError as e:
        db.rollback()
        return _err(e)
    return RequestService.request_out(db, req)
