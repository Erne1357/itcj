
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException

from itcj2.apps.prorrogas_tec.models.prorrogas_period_config import ProrrogasPeriodConfig
from itcj2.apps.prorrogas_tec.schemas.periods import ProrrogasPeriodConfigBase, ProrrogasPeriodConfigUpdate, ProrrogasPeriodConfigCreate, ProrrogasPeriodConfigOut
from itcj2.core.models.academic_period import AcademicPeriod
from itcj2.database import get_db
from itcj2.dependencies import require_roles
from sqlalchemy.orm import Session, joinedload

# ---------------------------------------------------------------------------
# Guard a nivel de ROUTER, no por endpoint.
#
# La app llego del fork con estos endpoints SIN autenticacion de ningun tipo
# (los `require_perms` estaban comentados): crear/editar/borrar periodos y
# listar/editar TODAS las solicitudes y pagos respondian a cualquiera sin
# sesion. Se cierra con el rol `admin` de la app, que es el minimo que no
# obliga a inventar el arbol de permisos antes de que la app este terminada.
#
# Va en el router y no en cada firma A PROPOSITO: un endpoint nuevo nace
# cerrado sin que nadie tenga que acordarse de ponerle el guard.
#
# TODO(prorrogas): sustituir por `require_perms("prorrogas_tec", [...])` con
# permisos granulares `prorrogas_tec.{modulo}.api.{accion}` cuando el modelo de
# roles de la app este definido. Ver itcj2/apps/prorrogas_tec/docs/PENDIENTES.md
# ---------------------------------------------------------------------------
router = APIRouter(
    tags=["prorrogas_tec-periods"],
    dependencies=[require_roles("prorrogas_tec", ["admin"])],
)
logger = logging.getLogger(__name__)

@router.get("/")
def list_periods2(db: Session = Depends(get_db)):
    items = db.query(ProrrogasPeriodConfig).all()

    result = []

    for p in items:
        result.append({
            "id": p.id,
            "period_id": p.period_id,
            "student_admission_start": p.student_admission_start,
            "student_admission_deadline": p.student_admission_deadline,
            "payment_1": p.payment_1,
            "payment_2": p.payment_2,
            "payment_3": p.payment_3,
            "period": p.period.to_dict() if p.period else None
        })

    return result
        
@router.post("/", response_model=ProrrogasPeriodConfigOut, name="create_period")
def create_period2(data: ProrrogasPeriodConfigCreate, db: Session = Depends(get_db)):

    if data.student_admission_deadline < data.student_admission_start:
        raise HTTPException(
            status_code=400,
            detail="La fecha límite debe ser mayor que la fecha inicio"
        )

    existing = db.query(ProrrogasPeriodConfig)\
        .filter(ProrrogasPeriodConfig.period_id == data.period_id)\
        .first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail="Ya existe un periodo para este period_id"
        )

    new_period = ProrrogasPeriodConfig(**data.dict())
    db.add(new_period)
    db.commit()
    db.refresh(new_period)

    return new_period


@router.patch("/{period_id}", response_model=ProrrogasPeriodConfigOut, name="update_period")
def update_period2(period_id: int, data: ProrrogasPeriodConfigUpdate, db: Session = Depends(get_db)):

    period = db.query(ProrrogasPeriodConfig)\
        .filter(ProrrogasPeriodConfig.id == period_id)\
        .first()

    if not period:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")

    start = data.student_admission_start or period.student_admission_start
    deadline = data.student_admission_deadline or period.student_admission_deadline

    if deadline < start:
        raise HTTPException(
            status_code=400,
            detail="La fecha límite debe ser mayor que la fecha inicio"
        )

    for key, value in data.dict(exclude_unset=True).items():
        setattr(period, key, value)

    db.commit()
    db.refresh(period)

    return period


@router.get("/academic-periods", name="academic_periods")
def list_academic_periods(db: Session = Depends(get_db)):

    periods = db.query(AcademicPeriod)\
        .filter(AcademicPeriod.status != "ARCHIVED")\
        .order_by(AcademicPeriod.start_date.desc())\
        .all()

    return [p.to_dict() for p in periods]


@router.get("/{period_id}", response_model=ProrrogasPeriodConfigOut, name="get_period")
def get_period(period_id: int, db: Session = Depends(get_db)):

    period = db.query(ProrrogasPeriodConfig)\
        .filter(ProrrogasPeriodConfig.id == period_id)\
        .first()

    if not period:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")

    return period


@router.delete("/{period_id}", name="delete_period")
def delete_period2(period_id: int, db: Session = Depends(get_db)):

    period = db.query(ProrrogasPeriodConfig)\
        .filter(ProrrogasPeriodConfig.id == period_id)\
        .first()

    if not period:
        raise HTTPException(status_code=404, detail="Periodo no encontrado")

    db.delete(period)
    db.commit()



# @router.delete("/{period_id}", status_code=204)
# def delete_period(
#     period_id: int,
#     user: dict = require_perms("agendatec", ["agendatec.periods.api.delete"]),
#     db: DbSession = None,
# ):
#     """Elimina un período. Solo si no tiene solicitudes vinculadas."""
#     period = db.query(AcademicPeriod).filter_by(id=period_id).first()
#     if not period:
#         raise HTTPException(status_code=404, detail="period_not_found")

#     request_count = period_service.count_requests_in_period(db, period_id)
#     if request_count > 0:
#         raise HTTPException(
#             status_code=409,
#             detail={
#                 "error": "period_has_requests",
#                 "message": f"El período tiene {request_count} solicitud(es). Use ARCHIVED en su lugar.",
#                 "request_count": request_count,
#             },
#         )

#     db.delete(period)
#     db.commit()
