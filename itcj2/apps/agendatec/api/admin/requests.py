"""
Admin Requests API v2 — Gestión de solicitudes (admin).
Fuente: itcj/apps/agendatec/routes/api/admin/requests.py
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.agendatec.helpers import parse_range_from_params
from itcj2.apps.agendatec.schemas.admin import ChangeRequestStatusBody, AdminCreateRequestBody
from itcj2.apps.agendatec.models.appointment import Appointment
from itcj2.apps.agendatec.models.request import Request as Req
from itcj2.apps.agendatec.models.time_slot import TimeSlot
from itcj2.core.models.coordinator import Coordinator
from itcj2.core.models.program import Program
from itcj2.core.models.program_coordinator import ProgramCoordinator
from itcj2.core.models.user import User
from itcj2.core.services import period_service
from itcj2.core.utils.notify import create_notification

router = APIRouter(tags=["agendatec-admin-requests"])
logger = logging.getLogger(__name__)

ReadPerm = require_perms("agendatec", ["agendatec.requests.api.read.all"])
UpdatePerm = require_perms("agendatec", ["agendatec.requests.api.update.all"])
CreatePerm = require_perms("agendatec", ["agendatec.requests.api.create.all"])


# ==================== GET /requests ====================

@router.get("/requests")
def admin_list_requests(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    program_id: Optional[int] = Query(None),
    coordinator_id: Optional[int] = Query(None),
    period_id: Optional[int] = Query(None),
    q: str = Query(""),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: dict = ReadPerm,
    db: DbSession = None,
):
    """Lista solicitudes con filtros y paginación."""
    start, end = parse_range_from_params(from_, to)

    qry = (
        db.query(Req)
        .options(
            joinedload(Req.appointment).joinedload(Appointment.coordinator).joinedload(Coordinator.user),
            joinedload(Req.program).joinedload(Program.program_coordinators)
                .joinedload(ProgramCoordinator.coordinator).joinedload(Coordinator.user),
            joinedload(Req.student),
        )
        .filter(Req.created_at >= start, Req.created_at <= end)
    )

    if status:
        qry = qry.filter(Req.status == status)
    if program_id:
        qry = qry.filter(Req.program_id == program_id)
    if coordinator_id:
        qry = qry.join(Appointment, Appointment.request_id == Req.id).filter(
            Appointment.coordinator_id == coordinator_id
        )
    if period_id:
        qry = qry.filter(Req.period_id == period_id)
    if q.strip():
        qry = qry.join(User, User.id == Req.student_id).filter(
            or_(
                User.control_number.ilike(f"%{q}%"),
                User.username.ilike(f"%{q}%"),
                User.full_name.ilike(f"%{q}%"),
            )
        )

    total = qry.order_by(None).count()
    items = qry.order_by(Req.created_at.desc()).limit(limit).offset(offset).all()

    def _to_dict(r: Req):
        a: Optional[Appointment] = r.appointment
        coord_name = None
        coord_id_val = None

        if a and a.coordinator and a.coordinator.user:
            coord_name = a.coordinator.user.full_name
            coord_id_val = a.coordinator_id
        elif r.program and r.program.program_coordinators:
            first = r.program.program_coordinators[0] if r.program.program_coordinators else None
            if first and first.coordinator and first.coordinator.user:
                coord_name = first.coordinator.user.full_name
                coord_id_val = first.coordinator.id

        return {
            "id": r.id,
            "type": r.type,
            "status": r.status,
            "program": r.program.name if r.program else None,
            "student": r.student.full_name if r.student else None,
            "student_control_number": (
                r.student.control_number if r.student and r.student.control_number
                else (r.student.username if r.student else None)
            ),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "coordinator_name": coord_name,
            "coordinator_id": coord_id_val,
            "appointment": {
                "id": a.id,
                "status": a.status,
                "coordinator_id": a.coordinator_id,
                "coordinator_name": coord_name,
                "time_slot_id": a.slot_id,
            } if a else None,
        }

    return {"items": [_to_dict(x) for x in items], "total": total}


# ==================== PATCH /requests/<req_id>/status ====================

@router.patch("/requests/{req_id}/status")
def admin_change_request_status(
    req_id: int,
    body: ChangeRequestStatusBody,
    user: dict = UpdatePerm,
    db: DbSession = None,
):
    """Cambia el estado de una solicitud."""
    from itcj2.apps.agendatec.services.request_ops import admin_change_request_status as change_status

    actor_id = int(user.get("sub")) if user.get("sub") else None
    resp, code = change_status(
        db,
        actor_user_id=actor_id,
        req_id=req_id,
        new_status=body.status,
        reason=body.reason or "",
    )
    if code >= 400:
        raise HTTPException(status_code=code, detail=resp)
    return resp


# ==================== GET /requests/<req_id> ====================

@router.get("/requests/{req_id}")
def admin_get_request_detail(
    req_id: int,
    user: dict = ReadPerm,
    db: DbSession = None,
):
    """Obtiene los detalles completos de una solicitud."""
    r = (
        db.query(Req)
        .options(
            joinedload(Req.appointment).joinedload(Appointment.coordinator).joinedload(Coordinator.user),
            joinedload(Req.appointment).joinedload(Appointment.slot),
            joinedload(Req.program),
            joinedload(Req.student),
            joinedload(Req.period),
        )
        .filter(Req.id == req_id)
        .first()
    )
    if not r:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    a: Optional[Appointment] = r.appointment
    coord_name = None
    coord_email = None
    slot_info = None

    if a:
        if a.coordinator and a.coordinator.user:
            coord_name = a.coordinator.user.full_name
            coord_email = a.coordinator.user.email
        if a.slot:
            slot_info = {
                "day": a.slot.day.isoformat() if a.slot.day else None,
                "start_time": a.slot.start_time.strftime("%H:%M") if a.slot.start_time else None,
                "end_time": a.slot.end_time.strftime("%H:%M") if a.slot.end_time else None,
            }

    return {
        "id": r.id,
        "type": r.type,
        "status": r.status,
        "description": r.description,
        "coordinator_comment": r.coordinator_comment,
        "program": r.program.name if r.program else None,
        "program_id": r.program_id,
        "period": r.period.name if r.period else None,
        "period_id": r.period_id,
        "student": {
            "id": r.student.id if r.student else None,
            "name": r.student.full_name if r.student else None,
            "control_number": (
                r.student.control_number if r.student and r.student.control_number
                else (r.student.username if r.student else None)
            ),
            "email": r.student.email if r.student else None,
        },
        "coordinator": {"name": coord_name, "email": coord_email} if coord_name else None,
        "appointment": {
            "id": a.id,
            "status": a.status,
            "booked_at": a.booked_at.isoformat() if a.booked_at else None,
            "slot": slot_info,
        } if a else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


# ==================== POST /requests/create ====================

@router.post("/requests/create")
def admin_create_request(
    body: AdminCreateRequestBody,
    user: dict = CreatePerm,
    db: DbSession = None,
):
    """Permite a un admin crear una solicitud en nombre de un estudiante."""
    req_type = (body.type or "").upper()
    if req_type not in ("APPOINTMENT", "DROP"):
        raise HTTPException(status_code=400, detail="invalid_type")

    student = db.query(User).get(body.student_id)
    if not student:
        raise HTTPException(status_code=404, detail="student_not_found")

    period = period_service.get_active_period(db)
    if not period:
        raise HTTPException(status_code=503, detail="no_active_period")

    existing = (
        db.query(Req)
        .filter(
            Req.student_id == body.student_id,
            Req.period_id == period.id,
            Req.status != "CANCELED",
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "already_has_request_in_period",
                "existing_request_id": existing.id,
                "existing_request_status": existing.status,
            },
        )

    if req_type == "DROP":
        r = Req(
            student_id=body.student_id,
            program_id=body.program_id,
            period_id=period.id,
            description=body.description.strip(),
            type="DROP",
            status="PENDING",
        )
        db.add(r)
        db.commit()

        try:
            coord_ids = [
                row[0]
                for row in db.query(ProgramCoordinator.coordinator_id)
                .filter_by(program_id=body.program_id)
                .all()
            ]
            from itcj2.core.sockets.requests import broadcast_drop_created
            for cid in coord_ids:
                broadcast_drop_created(None, cid, {
                    "request_id": r.id,
                    "student_id": body.student_id,
                    "program_id": body.program_id,
                    "status": r.status,
                })
        except Exception:
            logger.exception("Failed to broadcast drop_created")

        try:
            n = create_notification(
                user_id=body.student_id,
                type="DROP_CREATED",
                title="Solicitud de baja creada",
                body="Tu solicitud de baja fue registrada por un administrador.",
                data={"request_id": r.id},
                source_request_id=r.id,
                program_id=body.program_id,
            )
            db.commit()
            from itcj2.core.sockets.notifications import push_notification
            push_notification(None, body.student_id, n.to_dict())
        except Exception:
            logger.exception("Failed to create/push DROP notification")

        return {"ok": True, "request_id": r.id, "type": "DROP"}

    # APPOINTMENT
    if not body.slot_id:
        raise HTTPException(status_code=400, detail="slot_id_required")

    slot = db.query(TimeSlot).get(body.slot_id)
    if not slot or slot.is_booked:
        raise HTTPException(status_code=409, detail="slot_unavailable")

    enabled_days = set(period_service.get_enabled_days(db, period.id))
    if slot.day not in enabled_days:
        raise HTTPException(status_code=400, detail="day_not_enabled")

    if datetime.now() > datetime.combine(slot.day, slot.start_time):
        raise HTTPException(status_code=400, detail="slot_time_passed")

    link = (
        db.query(ProgramCoordinator)
        .filter(
            ProgramCoordinator.program_id == body.program_id,
            ProgramCoordinator.coordinator_id == slot.coordinator_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=400, detail="slot_not_for_program")

    try:
        updated = (
            db.query(TimeSlot)
            .filter(TimeSlot.id == body.slot_id, TimeSlot.is_booked == False)
            .update({TimeSlot.is_booked: True}, synchronize_session=False)
        )
        if updated != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="slot_conflict")

        r = Req(
            student_id=body.student_id,
            program_id=body.program_id,
            period_id=period.id,
            description=body.description.strip(),
            type="APPOINTMENT",
            status="PENDING",
        )
        db.add(r)
        db.flush()

        ap = Appointment(
            request_id=r.id,
            student_id=body.student_id,
            program_id=body.program_id,
            coordinator_id=slot.coordinator_id,
            slot_id=body.slot_id,
            status="SCHEDULED",
        )
        db.add(ap)
        db.commit()

        try:
            from itcj2.core.sockets.requests import broadcast_appointment_created
            day_str = str(slot.day)
            broadcast_appointment_created(None, ap.coordinator_id, day_str, {
                "request_id": r.id,
                "student_id": body.student_id,
                "program_id": body.program_id,
                "slot_day": day_str,
                "slot_start": slot.start_time.strftime("%H:%M"),
                "slot_end": slot.end_time.strftime("%H:%M"),
                "status": r.status,
            })
        except Exception:
            logger.exception("Failed to broadcast appointment_created")

        try:
            slot_day = str(slot.day)
            n = create_notification(
                user_id=body.student_id,
                type="APPOINTMENT_CREATED",
                title="Cita agendada",
                body=f"Tu cita fue agendada: {slot_day} {slot.start_time.strftime('%H:%M')}–{slot.end_time.strftime('%H:%M')}",
                data={"request_id": r.id, "appointment_id": ap.id, "day": slot_day},
                source_request_id=r.id,
                source_appointment_id=ap.id,
                program_id=body.program_id,
            )
            db.commit()
            from itcj2.core.sockets.notifications import push_notification
            push_notification(None, body.student_id, n.to_dict())
        except Exception:
            logger.exception("Failed to create/push APPOINTMENT notification")

        return {"ok": True, "request_id": r.id, "appointment_id": ap.id, "type": "APPOINTMENT"}

    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="conflict")
