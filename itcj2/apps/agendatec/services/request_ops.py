"""
Operaciones administrativas sobre solicitudes de AgendaTec.
Migrado de itcj/apps/agendatec/services/request_ops.py (Flask) a SQLAlchemy puro.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from itcj2.apps.agendatec.models.appointment import Appointment
from itcj2.apps.agendatec.models.audit_log import AuditLog
from itcj2.apps.agendatec.models.request import Request
from itcj2.apps.agendatec.models.time_slot import TimeSlot
from itcj2.core.models.program_coordinator import ProgramCoordinator
from itcj2.core.models.user import User
from itcj2.core.services.notification_service import NotificationService
from itcj2.sockets.notifications import push_notification
from itcj2.sockets.requests import broadcast_request_status_changed
from itcj2.utils import async_broadcast as _async_broadcast

logger = logging.getLogger(__name__)

_ALLOWED_FROM_PENDING = {
    "RESOLVED_SUCCESS", "RESOLVED_NOT_COMPLETED",
    "NO_SHOW", "ATTENDED_OTHER_SLOT", "CANCELED"
}

_TITLE_MAP = {
    "RESOLVED_SUCCESS": "Tu solicitud fue atendida y resuelta",
    "RESOLVED_NOT_COMPLETED": "Tu solicitud fue atendida pero no se resolvió",
    "NO_SHOW": "Marcado como no asistió",
    "ATTENDED_OTHER_SLOT": "Asististe en otro horario",
    "CANCELED": "Tu solicitud fue cancelada",
}
_TYPE_LABEL = {"APPOINTMENT": "CITA", "DROP": "BAJA"}



def admin_change_request_status(
    db: Session,
    *,
    actor_user_id: int | None,
    req_id: int,
    new_status: str,
    reason: str | None = None,
):
    """
    Cambia el estado de una Request desde el rol admin, sincronizando Appointment/Slot,
    generando audit log, notificando al alumno y emitiendo sockets a coordinadores.
    Devuelve dict con resumen de cambios.
    """
    new_status = (new_status or "").upper().strip()
    if not new_status:
        return {"error": "missing_status"}, 400

    r: Request | None = (
        db.query(Request)
        .options(joinedload(Request.appointment))
        .filter(Request.id == req_id)
        .with_for_update()
        .first()
    )
    if not r:
        return {"error": "not_found"}, 404

    old_status = r.status

    if r.status == "PENDING" and new_status not in _ALLOWED_FROM_PENDING:
        return {"error": "invalid_transition"}, 409
    if r.status != "PENDING" and new_status == "PENDING":
        return {"error": "invalid_transition"}, 409

    ap: Optional[Appointment] = r.appointment
    slot_day_str: Optional[str] = None
    if r.type == "APPOINTMENT" and ap:
        if new_status in ("RESOLVED_SUCCESS", "RESOLVED_NOT_COMPLETED", "ATTENDED_OTHER_SLOT"):
            ap.status = "DONE"
        elif new_status == "NO_SHOW":
            ap.status = "NO_SHOW"
        elif new_status == "CANCELED":
            ap.status = "CANCELED"
            slot = db.get(TimeSlot, ap.slot_id)
            if slot and slot.is_booked:
                slot.is_booked = False
                slot_day_str = str(slot.day)

    r.status = new_status

    db.add(
        AuditLog(
            actor_id=actor_user_id,
            entity="request",
            entity_id=r.id,
            action="admin_change_status",
            payload_json={"status": old_status},
        )
    )
    db.commit()

    # SOCKETS: avisar a coordinadores
    try:
        payload = {
            "type": r.type,
            "request_id": r.id,
            "new_status": r.status,
            "day": slot_day_str,
            "program_id": r.program_id,
        }
        if r.type == "APPOINTMENT" and ap:
            _async_broadcast(broadcast_request_status_changed(ap.coordinator_id, payload))
        else:
            coord_ids = [
                row[0]
                for row in db.query(ProgramCoordinator.coordinator_id)
                .filter_by(program_id=r.program_id)
                .all()
            ]
            for cid in coord_ids:
                _async_broadcast(broadcast_request_status_changed(cid, payload))
    except Exception:
        logger.exception("Failed to broadcast request_status_changed (admin)")

    # NOTIFICACIÓN al alumno
    try:
        stu_id = db.query(User.id).filter(User.id == r.student_id).scalar()
        if stu_id:
            n = NotificationService.create(
                db=db,
                user_id=stu_id,
                app_name="agendatec",
                type="REQUEST_STATUS_CHANGED",
                title=_TITLE_MAP.get(new_status, "Estado de solicitud actualizado"),
                body=(
                    f"Solicitud : {_TYPE_LABEL.get(r.type, '')}"
                    + (f"\nComentarios : {r.coordinator_comment}" if r.coordinator_comment else "")
                ),
                data={"request_id": r.id, "status": new_status},
                source_request_id=r.id,
                program_id=r.program_id,
            )
            db.commit()
            _async_broadcast(push_notification(stu_id, n.to_dict()))
    except Exception:
        logger.exception("Failed to create/push status-change notification (admin)")

    return {"ok": True, "old": old_status, "new": new_status}, 200
