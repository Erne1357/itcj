"""
Coord Drops API v2 — Gestión de bajas y estados de solicitudes.
Fuente: itcj/apps/agendatec/routes/api/coord/drops.py
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.agendatec.helpers import require_coordinator, get_coord_program_ids
from itcj2.apps.agendatec.schemas.coord import UpdateRequestStatusBody
from itcj.apps.agendatec.models.appointment import Appointment
from itcj.apps.agendatec.models.request import Request
from itcj.apps.agendatec.models.time_slot import TimeSlot
from itcj.core.models.user import User
from itcj.core.services import period_service
from itcj.core.utils.notify import create_notification

router = APIRouter(tags=["agendatec-coord-drops"])
logger = logging.getLogger(__name__)

ReadPerm = require_perms("agendatec", ["agendatec.drops.api.read.own"])
UpdatePerm = require_perms("agendatec", ["agendatec.appointments.api.update.own",
                                          "agendatec.drops.api.update.own"])

_ALLOWED_STATUSES = {"RESOLVED_SUCCESS", "RESOLVED_NOT_COMPLETED", "NO_SHOW", "ATTENDED_OTHER_SLOT", "CANCELED"}


# ==================== GET /drops ====================

@router.get("/drops")
def coord_drops(
    status: str = Query("ALL"),
    program_id: Optional[int] = Query(None),
    request_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = ReadPerm,
    db: DbSession = None,
):
    """Lista solicitudes de baja para los programas del coordinador."""
    coord_id = require_coordinator(int(user["sub"]), db)
    prog_ids = get_coord_program_ids(coord_id, db)

    if not prog_ids:
        return {"total": 0, "items": []}

    period = period_service.get_active_period()
    if not period:
        raise HTTPException(status_code=503, detail="no_active_period")

    status_upper = (status or "ALL").upper()

    q = (
        db.query(Request, User)
        .join(User, User.id == Request.student_id)
        .filter(
            Request.type == "DROP",
            Request.period_id == period.id,
            Request.program_id.in_(list(prog_ids)),
        )
    )

    if request_id:
        q = q.filter(Request.id == request_id)

    if status_upper != "ALL":
        q = q.filter(Request.status == status_upper)
    else:
        q = q.filter(Request.status != "CANCELED")

    if program_id:
        if program_id not in prog_ids:
            raise HTTPException(status_code=403, detail="forbidden_program")
        q = q.filter(Request.program_id == program_id)

    # Ordenar: pendientes primero
    if status_upper == "PENDING":
        q = q.order_by(Request.created_at.asc(), Request.id.asc())
    elif status_upper == "ALL":
        q = q.order_by(
            case((Request.status == "PENDING", 0), else_=1),
            Request.created_at.asc(),
            Request.id.asc(),
        )
    else:
        q = q.order_by(Request.created_at.asc(), Request.id.asc())

    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()

    items = [
        {
            "id": r.id,
            "status": r.status,
            "description": r.description,
            "created_at": r.created_at.isoformat(),
            "comment": r.coordinator_comment,
            "coordinator_comment": r.coordinator_comment,
            "student": {
                "id": u.id,
                "full_name": u.full_name,
                "control_number": u.control_number,
                "username": u.username,
            },
        }
        for r, u in rows
    ]

    return {
        "period": {
            "id": period.id,
            "name": period.name,
            "start_date": period.start_date.isoformat(),
            "end_date": period.end_date.isoformat(),
        },
        "total": total,
        "items": items,
    }


# ==================== PATCH /requests/<req_id>/status ====================

@router.patch("/requests/{req_id}/status")
async def update_request_status(
    req_id: int,
    body: UpdateRequestStatusBody,
    user: dict = UpdatePerm,
    db: DbSession = None,
):
    """Actualiza el estado de una solicitud (DROP o APPOINTMENT)."""
    coord_id = require_coordinator(int(user["sub"]), db)

    r = db.query(Request).get(req_id)
    if not r:
        raise HTTPException(status_code=404, detail="request_not_found")

    new_status = (body.status or "").upper()
    if new_status not in _ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="invalid_status")

    prog_ids = get_coord_program_ids(coord_id, db)
    if r.program_id not in prog_ids:
        raise HTTPException(status_code=403, detail="forbidden_program")

    if body.coordinator_comment is not None:
        r.coordinator_comment = body.coordinator_comment.strip() or None

    r.status = new_status

    if r.type == "APPOINTMENT":
        ap = db.query(Appointment).filter(Appointment.request_id == r.id).first()
        if ap:
            if new_status in ("RESOLVED_SUCCESS", "RESOLVED_NOT_COMPLETED", "ATTENDED_OTHER_SLOT"):
                ap.status = "DONE"
            elif new_status == "NO_SHOW":
                ap.status = "NO_SHOW"
            elif new_status == "CANCELED":
                ap.status = "CANCELED"
                slot = db.query(TimeSlot).get(ap.slot_id)
                if slot and slot.is_booked:
                    slot.is_booked = False

    db.commit()

    # WS: broadcast cambio de estado de la solicitud
    try:
        from itcj2.sockets.requests import broadcast_request_status_changed
        day = None
        if r.type == "APPOINTMENT":
            ap = db.query(Appointment).filter(Appointment.request_id == r.id).first()
            if ap:
                s = db.query(TimeSlot).get(ap.slot_id)
                day = str(s.day) if s else None
        await broadcast_request_status_changed(coord_id, {
            "type": r.type,
            "request_id": r.id,
            "new_status": r.status,
            "day": day,
            "program_id": r.program.id if r.program else None,
        })
    except Exception:
        logger.exception("Failed to broadcast request_status_changed")

    # Notificación DB + WS push al estudiante
    try:
        stu_id = r.student_id
        if stu_id:
            title_map = {
                "RESOLVED_SUCCESS": "Tu solicitud fue atendida y resuelta",
                "RESOLVED_NOT_COMPLETED": "Tu solicitud fue atendida pero no se resolvió",
                "NO_SHOW": "Marcado como no asistió",
                "ATTENDED_OTHER_SLOT": "Asististe en otro horario",
                "CANCELED": "Tu solicitud fue cancelada",
            }
            type_map = {"APPOINTMENT": "CITA", "DROP": "BAJA"}
            n = create_notification(
                user_id=stu_id,
                type="REQUEST_STATUS_CHANGED",
                title=title_map.get(new_status, "Estado de solicitud actualizado"),
                body="Solicitud : " + type_map.get(r.type, "") +
                     (("\nComentarios : " + r.coordinator_comment) if r.coordinator_comment else " "),
                data={"request_id": r.id, "status": new_status},
                source_request_id=r.id,
                program_id=r.program_id,
            )
            db.commit()
            from itcj2.sockets.notifications import push_notification
            await push_notification(stu_id, n.to_dict())
    except Exception:
        logger.exception("Failed to create/push status-change notification")

    return {"ok": True}
