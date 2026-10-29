"""API de la secretaria: pestaña Estudiantes (lista, expediente y plan de pagos).

Rutas bajo ``/api/prorrogas/v2/estudiantes``.
"""
from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from itcj2.apps.prorrogas_tec.api._common import service_error_response as _err
from itcj2.apps.prorrogas_tec.services.account import money
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.formatting import parse_monto
from itcj2.apps.prorrogas_tec.services.payment_service import PaymentService
from itcj2.apps.prorrogas_tec.services.plan_service import PlanService
from itcj2.apps.prorrogas_tec.services.students_service import StudentsService
from itcj2.core.utils.timezone import db_now
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["prorrogas_tec-estudiantes"])

_READ = ["prorrogas_tec.requests.api.read.all"]
_PLAN = ["prorrogas_tec.plans.api.manage"]
_RECORD = ["prorrogas_tec.payments.api.record"]
_VOID = ["prorrogas_tec.payments.api.void"]


class ParcialidadIn(BaseModel):
    monto: str | int | float
    fecha: date


class PlanIn(BaseModel):
    total: str | int | float
    parcialidades: list[ParcialidadIn]


class ReciboIn(BaseModel):
    folio: str
    fecha: date
    monto: str | int | float


class AnularIn(BaseModel):
    motivo: str


@router.get("/periodos", name="prorrogas_tec.api.estudiantes.periodos")
def periodos(db: DbSession, user: dict = require_perms("prorrogas_tec", _READ)):
    return StudentsService.periodos(db, db_now().date())


@router.get("", name="prorrogas_tec.api.estudiantes.lista")
def lista(period_id: int, db: DbSession, q: str | None = None, filtro: str = "todos", page: int = 1,
          per_page: int = 25, user: dict = require_perms("prorrogas_tec", _READ)):
    try:
        return StudentsService.listar(db, period_id, q=q, filtro=filtro, page=page, per_page=per_page,
                                      today=db_now().date())
    except ServiceError as e:
        return _err(e)


@router.get("/reparto", name="prorrogas_tec.api.estudiantes.reparto")  # antes de /{request_id}
def reparto(total: str, n: int, user: dict = require_perms("prorrogas_tec", _READ)):
    try:
        return {"montos": [money(x) for x in PlanService.reparto(total, n)]}
    except ServiceError as e:
        return _err(e)


@router.get("/{request_id}", name="prorrogas_tec.api.estudiantes.expediente")
def expediente(request_id: int, db: DbSession, user: dict = require_perms("prorrogas_tec", _READ)):
    try:
        return StudentsService.expediente(db, request_id, db_now().date())
    except ServiceError as e:
        return _err(e)


@router.post("/{request_id}/plan", name="prorrogas_tec.api.estudiantes.plan")
def plan(request_id: int, body: PlanIn, db: DbSession, user: dict = require_perms("prorrogas_tec", _PLAN)):
    try:
        PlanService.confirm(db, request_id, int(user["sub"]), total=parse_monto(body.total),
                            parcialidades=[(parse_monto(p.monto), p.fecha) for p in body.parcialidades])
    except ServiceError as e:
        db.rollback()
        return _err(e)
    return StudentsService.expediente(db, request_id, db_now().date())


@router.post("/{request_id}/recibos", name="prorrogas_tec.api.estudiantes.recibo")
def recibo(request_id: int, body: ReciboIn, db: DbSession, user: dict = require_perms("prorrogas_tec", _RECORD)):
    try:
        PaymentService.record(db, request_id, int(user["sub"]), folio=body.folio, paid_on=body.fecha,
                              amount=body.monto)
    except ServiceError as e:
        db.rollback()
        return _err(e)
    return StudentsService.expediente(db, request_id, db_now().date())


@router.post("/{request_id}/recibos/{payment_id}/anular", name="prorrogas_tec.api.estudiantes.recibo_anular")
def recibo_anular(request_id: int, payment_id: int, body: AnularIn, db: DbSession,
                  user: dict = require_perms("prorrogas_tec", _VOID)):
    try:
        PaymentService.void(db, payment_id, int(user["sub"]), motivo=body.motivo, request_id=request_id)
    except ServiceError as e:
        db.rollback()
        return _err(e)
    return StudentsService.expediente(db, request_id, db_now().date())
