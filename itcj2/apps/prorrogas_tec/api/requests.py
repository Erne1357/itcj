"""
Admin Requests API v2 — Gestión de solicitudes (admin).
Fuente: itcj/apps/agendatec/routes/api/admin/requests.py
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, Session

from itcj2.apps.prorrogas_tec.models.payments import Payments_pro
from itcj2.apps.prorrogas_tec.models.prorrogas_period_config import ProrrogasPeriodConfig
from itcj2.apps.prorrogas_tec.schemas.payments import PaymentResponse, PaymentUpdate
from itcj2.apps.prorrogas_tec.schemas.requests import RequestProOut, RequestProUpdate
from itcj2.dependencies import DbSession, require_perms, require_roles
from itcj2.apps.agendatec.helpers import parse_range_from_params
from itcj2.apps.agendatec.schemas.admin import ChangeRequestStatusBody, AdminCreateRequestBody
from itcj2.apps.agendatec.models.appointment import Appointment
# from itcj2.apps.agendatec.models.request import Request as Req
from itcj2.apps.agendatec.models.time_slot import TimeSlot
from itcj2.core.models.coordinator import Coordinator
from itcj2.core.models.program import Program
from itcj2.core.models.program_coordinator import ProgramCoordinator
from itcj2.core.models.user import User
from itcj2.core.services import period_service
from itcj2.core.utils.notify import create_notification

from itcj2.apps.prorrogas_tec.models.request import Request_pro
from itcj2.database import get_db

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
    tags=["prorrogas_tec-admin-requests"],
    dependencies=[require_roles("prorrogas_tec", ["admin"])],
)
logger = logging.getLogger(__name__)

# ReadPerm = require_perms("agendatec", ["agendatec.requests.api.read.all"])
# UpdatePerm = require_perms("agendatec", ["agendatec.requests.api.update.all"])
# CreatePerm = require_perms("agendatec", ["agendatec.requests.api.create.all"])

from typing import List


@router.get("/", name="request")
def list_requests_admin(db: Session = Depends(get_db)):

    requests = db.query(Request_pro)\
        .options(
            joinedload(Request_pro.period),
            joinedload(Request_pro.student)
        )\
        .all()

    result = []

    for r in requests:
        result.append({
            "id": r.id,
            "student_id": r.student_id,

            # ✅ AQUÍ agregas el estudiante
            "student": {
                "id": r.student.id,
                "career": r.career.name,
                "control_number": r.student.control_number,
                "name": f"{r.student.first_name} {r.student.middle_name} {r.student.last_name}" # 👈 depende de tu modelo User
            } if r.student else None,

            "period": r.period.to_dict() if r.period else None,
            "status": r.status,
            "letter": r.letter,
            "created_at": r.created_at,
            "payments_terms": r.payments_terms
        })

    return result


@router.patch("/{request_id}", response_model=RequestProOut, name="update_request")
def update_request(request_id: int, data: RequestProUpdate, db: Session = Depends(get_db)):

    request = db.query(Request_pro)\
        .filter(Request_pro.id == request_id)\
        .first()

    if not request:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    
    old_status = request.status

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(request, key, value)

    # Si fue aprobada y antes no estaba aprobada
    if (
        data.status == "APPROVED"
        and old_status != "APPROVED"
    ):
        
        period = (
            db.query(ProrrogasPeriodConfig)
            .filter(ProrrogasPeriodConfig.period_id == request.period_id)
            .first()
        )

        if not period:
            raise HTTPException(
                status_code=404,
                detail="Periodo no encontrado"
            )

        # Evitar duplicados
        if not request.payments:
            
            payment_dates = [
                0,
                period.payment_1,
                period.payment_2,
                period.payment_3,
                ]

            request.amount = 3250
            amount_per_payment = (
                request.amount / request.payments_terms
            )

            for i in range(1, request.payments_terms + 1):

                payment = Payments_pro(
                    request_id=request.id,
                    period_id=request.period_id,
                    num_payments_terms=i,
                    amount=amount_per_payment,
                    expiration_date=payment_dates[i],
                    status="PENDING"
                )

                db.add(payment)
   
    elif data.status == "REJECTED":
        (
            db.query(Payments_pro)
            .filter(Payments_pro.request_id == request.id)
            .delete(synchronize_session=False)
        )


    db.commit()
    db.refresh(request)

    return request

from fastapi import HTTPException

@router.get("/{request_id}/payments")
def get_request_payments(
    request_id: int,
    db: Session = Depends(get_db)
):

    request = (
        db.query(Request_pro)
        .filter(Request_pro.id == request_id)
        .first()
    )

    if not request:
        raise HTTPException(
            status_code=404,
            detail="Solicitud no encontrada"
        )

    return {
    "items": [
        {
            "id": p.id,
            "num_payments_terms": p.num_payments_terms,
            "amount": float(p.amount),
            "status": p.status,
            "expiration_date": (
                p.expiration_date.isoformat()
                if p.expiration_date else None
            ),
            "payday": (
                p.payday.isoformat()
                if p.payday else None
            ),
            "admin_comment": p.admin_comment
        }
        for p in request.payments
    ]
}



@router.patch("/payments/{payment_id}",response_model=PaymentResponse)
def update_payment(payment_id: int,data: PaymentUpdate,db: Session = Depends(get_db)):

    payment = (db.query(Payments_pro)
        .filter(Payments_pro.id == payment_id)
        .first()
    )

    if not payment:
        raise HTTPException(
            status_code=404,
            detail="Pago no encontrado"
        )

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(payment, key, value)

    db.commit()
    db.refresh(payment)

    return payment
