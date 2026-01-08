# routes/api/requests.py
from datetime import date, datetime
from flask import Blueprint, request, jsonify, g, current_app
from sqlalchemy.exc import IntegrityError
from itcj.core.utils.decorators import api_auth_required, api_role_required, api_closed, api_app_required
from itcj.apps.agendatec.models import db
from itcj.core.models.user import User
from itcj.core.models.program import Program
from itcj.core.models.program_coordinator import ProgramCoordinator
from itcj.core.models.academic_period import AcademicPeriod
from itcj.apps.agendatec.models.time_slot import TimeSlot
from itcj.apps.agendatec.models.request import Request
from itcj.apps.agendatec.models.appointment import Appointment
import logging
from itcj.core.utils.redis_conn import get_redis
from itcj.core.sockets.requests import broadcast_appointment_created, broadcast_drop_created, broadcast_request_status_changed
from itcj.core.utils.notify import create_notification
from itcj.core.sockets.notifications import push_notification
from itcj.core.services import period_service

api_req_bp = Blueprint("api_requests", __name__)

# NOTA: ALLOWED_DAYS eliminado - ahora se obtiene dinámicamente del período activo

def _get_current_student():
    uid = g.current_user["sub"]
    u = db.session.query(User).get(uid)
    return u

@api_req_bp.get("/mine")
@api_auth_required
@api_app_required(app_key="agendatec", roles=["student"])
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

@api_req_bp.post("")
@api_closed
@api_auth_required
@api_app_required(app_key="agendatec", roles=["student"])
def create_request():
    u = _get_current_student()
    data = request.get_json(silent=True) or {}
    req_type = (data.get("type") or "").upper()
    socketio = current_app.extensions.get('socketio')

    # ==================== VALIDACIÓN DE PERÍODO ====================
    # Obtener período activo
    period = period_service.get_active_period()
    if not period:
        return jsonify({"error": "no_active_period", "message": "No hay un período académico activo"}), 503

    # Validar que el estudiante NO tenga ya una solicitud en este período
    # (excepto si está CANCELED, en ese caso sí puede crear otra)
    existing_request = (db.session.query(Request)
                       .filter(Request.student_id == u.id,
                               Request.period_id == period.id,
                               Request.status != "CANCELED")
                       .first())

    if existing_request:
        return jsonify({
            "error": "already_has_request_in_period",
            "message": f"Ya tienes una solicitud en el período '{period.name}'.",
            "existing_request_id": existing_request.id,
            "existing_request_status": existing_request.status
        }), 409
    # ================================================================

    if req_type == "DROP":
        r = Request(
            student_id=u.id,
            program_id=int(data.get("program_id")),
            period_id=period.id,  # NUEVO: vincular al período activo
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

    # ==================== VALIDACIÓN DE DÍA HABILITADO ====================
    # Obtener días habilitados del período activo
    enabled_days = set(period_service.get_enabled_days(period.id))

    if slot.day not in enabled_days:
        return jsonify({
            "error": "day_not_enabled",
            "message": "El día seleccionado no está habilitado para este período",
            "enabled_days": [d.isoformat() for d in sorted(enabled_days)]
        }), 400
    # =====================================================================
    
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

        r = Request(
            student_id=u.id,
            program_id=data.get("program_id"),
            period_id=period.id,  # NUEVO: vincular al período activo
            description=data.get("description"),
            type="APPOINTMENT",
            status="PENDING"
        )
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

@api_req_bp.patch("/<int:req_id>/cancel")
@api_closed
@api_auth_required
@api_app_required(app_key="agendatec", roles=["student"])
def cancel_request(req_id: int):
    u = _get_current_student()
    slot_day = 0
    r = (db.session.query(Request)
         .filter(Request.id == req_id, Request.student_id == u.id)
         .first())
    socketio = current_app.extensions.get('socketio')

    if not r:
        return jsonify({"error": "request_not_found"}), 404
    if r.status != "PENDING":
        return jsonify({"error": "not_pending", "message": "Solo se pueden cancelar solicitudes en estado PENDING"}), 400

    # ==================== VALIDACIONES DE CANCELACIÓN ====================
    # 1. Verificar que el período académico esté activo
    period = db.session.query(AcademicPeriod).filter_by(id=r.period_id).first()
    if period and period.status != "ACTIVE":
        return jsonify({
            "error": "period_closed",
            "message": f"No se puede cancelar porque el período '{period.name}' ya cerró."
        }), 403

    # 2. Si es APPOINTMENT, verificar que la cita no haya pasado
    if r.type == "APPOINTMENT":
        ap = db.session.query(Appointment).filter(Appointment.request_id == r.id).first()
        if ap:
            slot = db.session.query(TimeSlot).get(ap.slot_id)
            if slot:
                now = datetime.now()
                slot_datetime = datetime.combine(slot.day, slot.start_time)

                if now >= slot_datetime:
                    return jsonify({
                        "error": "appointment_time_passed",
                        "message": "No se puede cancelar porque la cita ya pasó."
                    }), 403
    # =====================================================================

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
