"""API de Caja: buscar solicitudes, saldar el pago más próximo y anular el último recibo.

Rutas bajo ``/api/prorrogas/v2/caja``. Toda ruta valida con ``CajaService.solicitud``.
"""
from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from itcj2.apps.prorrogas_tec.api._common import (
    recibo_pdf_response, referencia_pdf_response, service_error_response as _err)
from itcj2.apps.prorrogas_tec.services.caja_service import CajaService
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.payment_service import PaymentService
from itcj2.apps.prorrogas_tec.services.students_service import StudentsService
from itcj2.core.utils.timezone import db_now
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["prorrogas_tec-caja"])

_READ = ["prorrogas_tec.caja.api.read"]
_RECORD = ["prorrogas_tec.payments.api.record"]
_VOID = ["prorrogas_tec.payments.api.void"]


class SaldarIn(BaseModel):
    numero: int
    monto: str
    folio: str
    fecha: date


class AnularIn(BaseModel):
    motivo: str


@router.get("", name="prorrogas_tec.api.caja.lista")
def lista(db: DbSession, q: str | None = None, semestre: int | None = None, filtro: str = "todos",
          orden: str = "urgente", page: int = 1, user: dict = require_perms("prorrogas_tec", _READ)):
    try:
        return CajaService.listar(db, q=q, semestre=semestre, filtro=filtro, orden=orden, page=page,
                                  today=db_now().date())
    except ServiceError as e:
        return _err(e)


@router.get("/semestres", name="prorrogas_tec.api.caja.semestres")  # antes de /{request_id}
def semestres(db: DbSession, user: dict = require_perms("prorrogas_tec", _READ)):
    return {"items": StudentsService.periodos(db, db_now().date())["items"]}


@router.get("/{request_id}", name="prorrogas_tec.api.caja.detalle")
def detalle(request_id: int, db: DbSession, user: dict = require_perms("prorrogas_tec", _READ)):
    try:
        return CajaService.detalle(db, request_id, db_now().date())
    except ServiceError as e:
        return _err(e)


@router.get("/{request_id}/referencia.pdf", name="prorrogas_tec.api.caja.referencia")
def referencia(request_id: int, db: DbSession, user: dict = require_perms("prorrogas_tec", _READ)):
    return referencia_pdf_response(CajaService.solicitud(db, request_id))


@router.get("/{request_id}/parcialidades/{numero}/recibo.pdf", name="prorrogas_tec.api.caja.recibo_pdf")
def recibo_pdf(request_id: int, numero: int, db: DbSession, user: dict = require_perms("prorrogas_tec", _READ)):
    return recibo_pdf_response(db, CajaService.solicitud(db, request_id), numero)


@router.post("/{request_id}/saldar", name="prorrogas_tec.api.caja.saldar")
def saldar(request_id: int, body: SaldarIn, db: DbSession, user: dict = require_perms("prorrogas_tec", _RECORD)):
    try:
        if CajaService.solicitud(db, request_id) is None:
            raise ServiceError("no_encontrada", "No se encontró la solicitud.", status=404)
        PaymentService.settle_next(db, request_id, int(user["sub"]), numero=body.numero, monto=body.monto,
                                   folio=body.folio, paid_on=body.fecha)
    except ServiceError as e:
        db.rollback()
        return _err(e)
    return CajaService.detalle(db, request_id, db_now().date())


@router.post("/{request_id}/recibos/{payment_id}/anular", name="prorrogas_tec.api.caja.anular")
def anular(request_id: int, payment_id: int, body: AnularIn, db: DbSession,
           user: dict = require_perms("prorrogas_tec", _VOID)):
    try:
        if CajaService.solicitud(db, request_id) is None:
            raise ServiceError("no_encontrada", "No se encontró la solicitud.", status=404)
        PaymentService.void(db, payment_id, int(user["sub"]), motivo=body.motivo, request_id=request_id)
    except ServiceError as e:
        db.rollback()
        return _err(e)
    return CajaService.detalle(db, request_id, db_now().date())
