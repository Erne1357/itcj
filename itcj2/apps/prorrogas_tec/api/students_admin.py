"""API de la secretaria: pestaña Estudiantes (lectura).

Rutas bajo ``/api/prorrogas/v2/estudiantes``.
"""
from fastapi import APIRouter

from itcj2.apps.prorrogas_tec.api._common import service_error_response as _err
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.apps.prorrogas_tec.services.students_service import StudentsService
from itcj2.core.utils.timezone import db_now
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["prorrogas_tec-estudiantes"])

_READ = ["prorrogas_tec.requests.api.read.all"]


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


@router.get("/{request_id}", name="prorrogas_tec.api.estudiantes.expediente")
def expediente(request_id: int, db: DbSession, user: dict = require_perms("prorrogas_tec", _READ)):
    try:
        return StudentsService.expediente(db, request_id, db_now().date())
    except ServiceError as e:
        return _err(e)
