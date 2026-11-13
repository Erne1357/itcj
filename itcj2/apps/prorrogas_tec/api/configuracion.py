"""API de la secretaria: pestaña Configuración (periodo de Prórrogas de cada semestre).

Rutas bajo ``/api/prorrogas/v2/configuracion``.
"""
from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from itcj2.apps.prorrogas_tec.api._common import service_error_response as _err
from itcj2.apps.prorrogas_tec.services import periods
from itcj2.apps.prorrogas_tec.services.errors import ServiceError
from itcj2.core.utils.timezone import db_now
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["prorrogas_tec-configuracion"])

_READ = ["prorrogas_tec.requests.api.read.all"]
_WRITE = ["prorrogas_tec.plans.api.manage"]  # estas fechas llenan los planes: las define quien arma los planes


class PeriodoIn(BaseModel):
    abre: date
    cierra: date
    pago1: date
    pago2: date


@router.get("/periodos", name="prorrogas_tec.api.configuracion.periodos")
def lista(db: DbSession, user: dict = require_perms("prorrogas_tec", _READ)):
    return periods.configuracion(db, db_now().date())


@router.post("/periodos/{period_id}", name="prorrogas_tec.api.configuracion.guardar")
def guardar(period_id: int, body: PeriodoIn, db: DbSession, user: dict = require_perms("prorrogas_tec", _WRITE)):
    try:
        periods.guardar(db, period_id, int(user["sub"]), abre=body.abre, cierra=body.cierra,
                        pago1=body.pago1, pago2=body.pago2)
    except ServiceError as e:
        db.rollback()
        return _err(e)
    return periods.configuracion(db, db_now().date())
