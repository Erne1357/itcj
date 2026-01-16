# backend/services/request_ops.py
from __future__ import annotations
from typing import Optional, Iterable
from datetime import datetime
from flask import current_app
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from itcj.apps.agendatec.models import db
from itcj.core.models.user import User
from itcj.apps.agendatec.models.request import Request
from itcj.apps.agendatec.models.appointment import Appointment
from itcj.apps.agendatec.models.time_slot import TimeSlot
from itcj.core.models.program_coordinator import ProgramCoordinator
from itcj.apps.agendatec.models.audit_log import AuditLog
from itcj.core.sockets.requests import broadcast_request_status_changed
from itcj.core.utils.notify import create_notification
from itcj.core.sockets.notifications import push_notification


def _get_socketio():
    """Obtiene la instancia de SocketIO de la aplicación actual (evita import circular)."""
    return current_app.extensions.get("socketio")

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

def admin_change_request_status(*, actor_user_id: int|None, req_id: int, new_status: str, reason: str|None = None):
    """
    Cambia el estado de una Request desde el rol admin, sincronizando Appointment/Slot,
    generando audit log, notificando al alumno y emitiendo sockets a coordinadores.
    Devuelve dict con resumen de cambios.
    """
    new_status = (new_status or "").upper().strip()
    if not new_status:
        return {"error": "missing_status"}, 400

    r: Request | None = (
        db.session.query(Request)
        .options(joinedload(Request.appointment))
        .filter(Request.id == req_id)
        .with_for_update()
        .first()
    )
    if not r:
        return {"error": "not_found"}, 404

    old_status = r.status

    # Reglas mínimas: principalmente transiciones desde PENDING
    if r.status == "PENDING" and new_status not in _ALLOWED_FROM_PENDING:
        return {"error": "invalid_transition"}, 409
    if r.status != "PENDING" and new_status == "PENDING":
        return {"error": "invalid_transition"}, 409

    # Sincroniza Appointment si aplica
    ap: Optional[Appointment] = r.appointment
    slot_day_str: Optional[str] = None
    if r.type == "APPOINTMENT" and ap:
        # espejo de reglas que ya usas en coord.py
        if new_status in ("RESOLVED_SUCCESS", "RESOLVED_NOT_COMPLETED", "ATTENDED_OTHER_SLOT"):
            ap.status = "DONE"
        elif new_status == "NO_SHOW":
            ap.status = "NO_SHOW"
        elif new_status == "CANCELED":
            ap.status = "CANCELED"
            slot = db.session.query(TimeSlot).get(ap.slot_id)
            if slot and slot.is_booked:
                slot.is_booked = False
                slot_day_str = str(slot.day)

    r.status = new_status

    # Audit
    db.session.add(
        AuditLog(
            actor_id=actor_user_id,
            entity="request",
            entity_id=r.id,
            action="admin_change_status",
            payload_json={"status": old_status},
        )
    )
    db.session.commit()

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
            # a un coordinador específico
            broadcast_request_status_changed(_get_socketio(), ap.coordinator_id, payload)
        else:
            # DROP → a todos los coordinadores del programa
            coord_ids = [row[0] for row in db.session
                .query(ProgramCoordinator.coordinator_id)
                .filter_by(program_id=r.program_id).all()]
            for cid in coord_ids:
                broadcast_request_status_changed(_get_socketio(), cid, payload)
    except Exception:
        current_app.logger.exception("Failed to broadcast request_status_changed (admin)")

    # NOTIFICACIÓN al alumno
    try:
        stu_id = db.session.query(User.id).filter(User.id == r.student_id).scalar()
        if stu_id:
            n = create_notification(
                user_id=stu_id,
                type="REQUEST_STATUS_CHANGED",
                title=_TITLE_MAP.get(new_status, "Estado de solicitud actualizado"),
                body=f"Solicitud : {_TYPE_LABEL.get(r.type,'')}"
                     + (f"\nComentarios : {r.coordinator_comment}" if r.coordinator_comment else ""),
                data={"request_id": r.id, "status": new_status},
                source_request_id=r.id,
                program_id=r.program_id
            )
            db.session.commit()
            push_notification(_get_socketio(), stu_id, n.to_dict())
    except Exception:
        current_app.logger.exception("Failed to create/push status-change notification (admin)")

    return {"ok": True, "old": old_status, "new": new_status}, 200
