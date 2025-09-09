# sockets/requests.py
from flask import g, request,current_app
from flask_socketio import emit, join_room, leave_room
from itcj.core.utils.socket_auth import current_user_from_environ
import logging
from itcj.apps.agendatec.models import db

NAMESPACE = "/requests"

def _room_social_ap_day(day: str) -> str:
    return f"social:ap:{day}"

def _room_social_ap_day_prog(day: str, program_id: int) -> str:
    return f"social:ap:{day}:prog:{program_id}"

def _room_ap_day(coord_id: int, day: str) -> str:
    return f"coord:ap:{coord_id}:{day}"

def _room_drops(coord_id: int) -> str:
    return f"coord:drops:{coord_id}"

def register_request_events(socketio):
    @socketio.on("connect", namespace=NAMESPACE)
    def on_connect():
        user = current_user_from_environ(request.environ)
        if not user:
            return False
        g.current_user = user
        emit("hello", {"msg": "WS /requests conectado"})

    @socketio.on("disconnect", namespace=NAMESPACE)
    def on_disconnect(*args, **kwargs):
        try:
            # ... tu limpieza, por ejemplo:
            db.session.remove()
        except Exception:
            pass

    # -------- Appointments (por día) ----------
    @socketio.on("join_ap_day", namespace=NAMESPACE)
    def on_join_ap_day(data):
        # esperado: {"coord_id": <int>, "day":"YYYY-MM-DD"}
        try:
            coord_id = int((data or {}).get("coord_id") or 0)
            day = (data or {}).get("day") or ""
        except Exception:
            emit("error", {"error": "bad_payload"})
            return
        if coord_id <= 0 or not day:
            emit("error", {"error": "invalid_join_ap_day"})
            return
        join_room(_room_ap_day(coord_id, day))
        emit("joined_ap_day", {"coord_id": coord_id, "day": day})

    @socketio.on("leave_ap_day", namespace=NAMESPACE)
    def on_leave_ap_day(data):
        try:
            coord_id = int((data or {}).get("coord_id") or 0)
            day = (data or {}).get("day") or ""
        except Exception:
            emit("error", {"error": "bad_payload"})
            return
        if coord_id <= 0 or not day:
            emit("error", {"error": "invalid_leave_ap_day"})
            return
        leave_room(_room_ap_day(coord_id, day))
        emit("left_ap_day", {"coord_id": coord_id, "day": day})

    # -------- Drops (1 room por coordinador) ----------
    @socketio.on("join_drops", namespace=NAMESPACE)
    def on_join_drops(data):
        try:
            coord_id = int((data or {}).get("coord_id") or 0)
        except Exception:
            emit("error", {"error": "bad_payload"})
            return
        if coord_id <= 0:
            emit("error", {"error": "invalid_join_drops"})
            return
        join_room(_room_drops(coord_id))
        emit("joined_drops", {"coord_id": coord_id})
    @socketio.on("join_social_ap_day", namespace=NAMESPACE)
    def on_join_social_ap_day(data):
        day = (data or {}).get("day") or ""
        program_id = (data or {}).get("program_id")
        if not day:
            emit("error", {"error": "invalid_day"})
            return
        if program_id:
            try:
                pid = int(program_id)
            except Exception:
                emit("error", {"error": "invalid_program_id"})
                return
            join_room(_room_social_ap_day_prog(day, pid))
        else:
            join_room(_room_social_ap_day(day))
        emit("joined_social_ap_day", {"day": day, "program_id": program_id})

    @socketio.on("leave_social_ap_day", namespace=NAMESPACE)
    def on_leave_social_ap_day(data):
        day = (data or {}).get("day") or ""
        program_id = (data or {}).get("program_id")
        if not day:
            emit("error", {"error": "invalid_day"})
            return
        if program_id:
            try:
                pid = int(program_id)
            except Exception:
                emit("error", {"error": "invalid_program_id"})
                return
            leave_room(_room_social_ap_day_prog(day, pid))
        else:
            leave_room(_room_social_ap_day(day))
        emit("left_social_ap_day", {"day": day, "program_id": program_id})

# --------- Helpers para emitir desde rutas ----------
def broadcast_appointment_created(socketio, coord_id: int, day: str, payload: dict):
    socketio.emit("appointment_created", payload, to=_room_ap_day(coord_id, day), namespace=NAMESPACE)
    try:
        program_id = payload.get("program_id")
        socketio.emit("appointment_created", payload, to=_room_social_ap_day(day), namespace=NAMESPACE)
        if program_id:
            socketio.emit("appointment_created", payload,
                          to=_room_social_ap_day_prog(day, int(program_id)), namespace=NAMESPACE)
    except Exception:
        current_app.logger.warning("Error created : ")
        pass

def broadcast_drop_created(socketio, coord_id: int, payload: dict):
    socketio.emit("drop_created", payload, to=_room_drops(coord_id), namespace=NAMESPACE)

def broadcast_request_status_changed(socketio, coord_id: int, payload: dict):
    # Emitimos a ambas salas potenciales (citas del día y drops). El cliente decide si refresca.
    day = payload.get("day")
    if day:
        socketio.emit("request_status_changed", payload,
                      to=_room_ap_day(coord_id, day), namespace=NAMESPACE)
    socketio.emit("request_status_changed", payload,
                  to=_room_drops(coord_id), namespace=NAMESPACE)
    try:
        if payload.get("type") == "APPOINTMENT" and day:
            program_id = payload.get("program_id")
            socketio.emit("request_status_changed", payload, to=_room_social_ap_day(day), namespace=NAMESPACE)
            if program_id:
                socketio.emit("request_status_changed", payload,
                              to=_room_social_ap_day_prog(day, int(program_id)), namespace=NAMESPACE)
    except Exception :
        current_app.logger.warning("Error change : ")
        pass
