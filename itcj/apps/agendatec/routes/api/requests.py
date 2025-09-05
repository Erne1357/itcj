# routes/api/requests.py
from datetime import date
from flask import Blueprint, request, jsonify, g, current_app
from sqlalchemy.exc import IntegrityError
from .....core.utils.decorators import api_auth_required, api_role_required, api_closed
from ...models import db
from ...models.user import User
from ...models.program import Program
from ...models.program_coordinator import ProgramCoordinator
from ...models.time_slot import TimeSlot    # id, coordinator_id, day (DATE), start_time (TIME), is_booked
from ...models.request import Request
from ...models.appointment import Appointment
import logging
from .....core.sockets import socketio
from .....core.utils.redis_conn import get_redis
from .....core.sockets.requests import broadcast_appointment_created, broadcast_drop_created, broadcast_request_status_changed
from .....core.utils.notify import create_notification
from .....core.sockets.notifications import push_notification
from datetime import datetime
api_req_bp = Blueprint("api_requests", __name__)

# Días permitidos
ALLOWED_DAYS = {date(2025, 8, 25), date(2025, 8, 26), date(2025, 8, 27)}

def _get_current_student():
    uid = g.current_user["sub"]
    u = db.session.query(User).get(uid)
    return u

@api_req_bp.get("/requests/mine")
@api_auth_required
@api_role_required(["student"])
def my_requests():
    u = _get_current_student()
    active = (db.session.query(Request)
              .filter(Request.student_id == u.id, Request.status == "PENDING")
              .order_by(Request.created_at.desc())
              .first())
    history = (db.session.query(Request)
               .filter(Request.student_id == u.id, Request.status != "PENDING")
               .order_by(Request.created_at.desc())
               .limit(10).all())

    def to_dict(r: Request):
        item = {"id": r.id, "type": r.type,"description": r.description ,"status": r.status, "created_at": r.created_at.isoformat(), "comment" : r.coordinator_comment}
        if r.type == "APPOINTMENT":
            ap = db.session.query(Appointment).filter(Appointment.request_id == r.id).first()
            if ap:
                sl = db.session.query(TimeSlot).get(ap.slot_id)
                item["appointment"] = {
                    "id": ap.id,
                    "program_id": ap.program_id,
                    "coordinator_id": ap.coordinator_id,
                    "slot": {
                        "id": sl.id,
                        "day": sl.day.isoformat(),
                        "start_time": sl.start_time.isoformat(),
                        "end_time": sl.end_time.isoformat(),  
                        "is_booked": sl.is_booked
                    },
                    "status": ap.status
                }
        return item

    return jsonify({
        "active": to_dict(active) if active else None,
        "history": [to_dict(x) for x in history]
    })

@api_req_bp.post("/requests")
@api_closed
@api_auth_required
@api_role_required(["student"])
def create_request():
    u = _get_current_student()
    data = request.get_json(silent=True) or {}
    req_type = (data.get("type") or "").upper()

    exists = (db.session.query(Request)
              .filter(Request.student_id == u.id)
              .first())
    if exists and exists.status != "CANCELED":
        return jsonify({"error": "already_has_petition"}), 409

    if req_type == "DROP":
        r = Request(
            student_id=u.id,
            program_id=int(data.get("program_id")),
            description=data.get("description"),
            type="DROP",
            status="PENDING"
        )
        db.session.add(r)
        db.session.commit()

        #  Avisar a TODOS los coordinadores vinculados al programa
        try:
            coord_ids = [
                row[0] for row in db.session.query(ProgramCoordinator.coordinator_id)
                                        .filter_by(program_id=r.program_id).all()
            ]
            payload = {
                "request_id": r.id,
                "student_id": u.id,
                "program_id": r.program_id,
                "status": r.status  # PENDING
            }
            for cid in coord_ids:
                broadcast_drop_created(socketio, cid, payload)
        except Exception:
            current_app.logger.exception("Failed to broadcast drop_created")
        
        #Enviar la notificación al alumno
        try:
            n = create_notification(
                user_id=u.id,
                type="DROP_CREATED",
                title="Solicitud de baja creada",
                body="Tu solicitud de baja fue registrada.",
                data={"request_id": r.id},
                source_request_id=r.id,
                program_id=r.program_id
            )
            db.session.commit()
            push_notification(socketio, u.id, n.to_dict())
        except Exception:
            current_app.logger.exception("Failed to create/push DROP notification")
        return jsonify({"ok": True, "request_id": r.id})

    if req_type != "APPOINTMENT":
        return jsonify({"error": "invalid_type"}), 400

    try:
        program_id = int(data.get("program_id"))
        slot_id = int(data.get("slot_id"))
    except Exception:
        return jsonify({"error": "invalid_payload"}), 400

    prog = db.session.query(Program).get(program_id)
    if not prog:
        return jsonify({"error": "program_not_found"}), 404

    slot = db.session.query(TimeSlot).get(slot_id)
    if not slot or slot.is_booked:
        return jsonify({"error": "slot_unavailable"}), 409

    
    # Día permitido (directo desde slot.day)
    if slot.day not in ALLOWED_DAYS:
        return jsonify({"error": "day_not_allowed", "allowed": [str(x) for x in sorted(ALLOWED_DAYS)]}), 400
    
    now = datetime.now()
    slot_datetime = datetime.combine(slot.day, slot.start_time)
    if now > slot_datetime:
        return jsonify({"error": "slot_time_passed"}), 400
    
    # El coordinador del slot debe estar vinculado al programa
    link = (db.session.query(ProgramCoordinator)
            .filter(ProgramCoordinator.program_id == program_id,
                    ProgramCoordinator.coordinator_id == slot.coordinator_id)
            .first())
    if not link:
        return jsonify({"error": "slot_not_for_program"}), 400

    # Transacción "gana el primero": reserva si sigue libre
    try:
        updated = (db.session.query(TimeSlot)
                   .filter(TimeSlot.id == slot_id, TimeSlot.is_booked == False)
                   .update({TimeSlot.is_booked: True}, synchronize_session=False))
        if updated != 1:
            db.session.rollback()
            return jsonify({"error": "slot_conflict"}), 409

        r = Request(student_id=u.id, program_id = data.get("program_id"),description = data.get("description"), type="APPOINTMENT", status="PENDING")
        db.session.add(r)
        db.session.flush()

        ap = Appointment(
            request_id=r.id,
            student_id=u.id,
            program_id=program_id,
            coordinator_id=slot.coordinator_id,
            slot_id=slot_id,
            status="SCHEDULED"
        )
        db.session.add(ap)
        db.session.commit()
        #Ajuste a los slots
        try:
            slot_day = str(slot.day)  # 'slot' ya lo tienes cargado arriba
            room = f"day:{slot_day}"
            socketio.emit("slot_booked", {
                "slot_id": slot_id,
                "day": slot_day,
                "start_time": slot.start_time.strftime("%H:%M"),
                "end_time": slot.end_time.strftime("%H:%M"),
            }, to=room, namespace="/slots")
            # Borrar hold si existía
            redis_cli = get_redis()
            redis_cli.delete(f"slot:{slot_id}:hold")
        except Exception as e:
            # No rompas el flujo si el broadcast falla
            current_app.logger.exception("Failed to broadcast slot_booked")

        try:
            day_str = str(slot.day)
            payload = {
                "request_id": r.id,
                "student_id": u.id,
                "program_id": program_id,
                "slot_day": day_str,
                "slot_start": slot.start_time.strftime("%H:%M"),
                "slot_end":   slot.end_time.strftime("%H:%M"),
                "status": r.status  # PENDING
            }
            broadcast_appointment_created(socketio, ap.coordinator_id, day_str, payload)
        except Exception:
            current_app.logger.exception("Failed to broadcast appointment_created")

        # Notificar al alumno
        try:
            n = create_notification(
                user_id=u.id,  
                type="APPOINTMENT_CREATED",
                title="Cita agendada",
                body=f"{slot_day} {slot.start_time.strftime('%H:%M')}–{slot.end_time.strftime('%H:%M')}",
                data={"request_id": r.id, "appointment_id": ap.id, "day": slot_day},
                source_request_id=r.id,
                source_appointment_id=ap.id,
                program_id=program_id
            )
            db.session.commit()
            push_notification(socketio, u.id, n.to_dict())
        except Exception:
            current_app.logger.exception("Failed to create/push APPOINTMENT notification")


        return jsonify({"ok": True, "request_id": r.id, "appointment_id": ap.id})
        

    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "conflict"}), 409

@api_req_bp.patch("/requests/<int:req_id>/cancel")
@api_closed
@api_auth_required
@api_role_required(["student"])
def cancel_request(req_id: int):
    u = _get_current_student()
    slot_day = 0
    r = (db.session.query(Request)
         .filter(Request.id == req_id, Request.student_id == u.id)
         .first())
    if not r:
        return jsonify({"error": "request_not_found"}), 404
    if r.status != "PENDING":
        return jsonify({"error": "not_pending"}), 400

    if r.type == "APPOINTMENT":
        ap = db.session.query(Appointment).filter(Appointment.request_id == r.id).first()
        if ap:
            slot = db.session.query(TimeSlot).get(ap.slot_id)
            if slot and slot.is_booked:
                slot_day = str(slot.day)
                slot.is_booked = False
            ap.status = "CANCELED"

    r.status = "CANCELED"
    db.session.commit()
    try:
        room = f"day:{slot_day}"
        socketio.emit("slot_released", {
            "slot_id": ap.slot_id,
            "day": slot_day,
            "start_time": slot.start_time.strftime("%H:%M"),
            "end_time": slot.end_time.strftime("%H:%M"),
        }, to=room, namespace="/slots")
        # Borrar hold si existía
        redis_cli = get_redis()
        redis_cli.delete(f"slot:{ap.slot_id}:hold")
    except Exception as e:
        # No rompas el flujo si el broadcast falla
        current_app.logger.exception("Failed to broadcast slot_booked")
    
    try:
        if r.type == "APPOINTMENT":
            # ap y slot existen si era cita
            day_str = str(slot.day) if 'slot' in locals() and slot else None
            payload = {
                "type": "APPOINTMENT",
                "request_id": r.id,
                "new_status": r.status,  # CANCELED
                "day": day_str,
                "program_id" : r.program.id
            }
            # ap existe si era cita
            if 'ap' in locals() and ap:
                broadcast_request_status_changed(socketio, ap.coordinator_id, payload)
        else:
            # DROP → avisar a TODOS los coordinadores del programa
            coord_ids = [
                row[0] for row in db.session.query(ProgramCoordinator.coordinator_id)
                                        .filter_by(program_id=r.program_id).all()
            ]
            payload = {
                "type": "DROP",
                "request_id": r.id,
                "new_status": r.status,  # CANCELED
                "day": None
            }
            for cid in coord_ids:
                broadcast_request_status_changed(socketio, cid, payload)
    except Exception:
        current_app.logger.exception("Failed to broadcast request_status_changed")
    
    #Notificar al alumno sobre su cancelación
    try:
        n = create_notification(
            user_id=u.id,
            type="APPOINTMENT_CANCELED" if r.type == "APPOINTMENT" else "REQUEST_STATUS_CHANGED",
            title="Solicitud cancelada",
            body="Has cancelado tu solicitud.",
            data={"request_id": r.id},
            source_request_id=r.id,
            program_id=r.program_id
        )
        db.session.commit()
        push_notification(socketio, u.id, n.to_dict())
    except Exception:
        current_app.logger.exception("Failed to create/push CANCEL notification")
    
    return jsonify({"ok": True})
