"""
WebSocket namespace /requests para solicitudes de AgendaTec.

Migración de itcj/core/sockets/requests.py (Flask-SocketIO sync)
a python-socketio ASGI (async nativo).
"""
import asyncio
import logging

from itcj2.core.utils.socket_auth import current_user_from_environ

from .server import sio

logger = logging.getLogger("itcj2.sockets.requests")

NAMESPACE = "/requests"


# ==================== Room Helpers ====================

def _room_social_ap_day(day: str) -> str:
    return f"social:ap:{day}"


def _room_social_ap_day_prog(day: str, program_id: int) -> str:
    return f"social:ap:{day}:prog:{program_id}"


def _room_ap_day(coord_id: int, day: str) -> str:
    return f"coord:ap:{coord_id}:{day}"


def _room_drops(coord_id: int) -> str:
    return f"coord:drops:{coord_id}"


# ==================== Async Broadcast Functions ====================

async def broadcast_appointment_created(coord_id: int, day: str, payload: dict):
    """Broadcast cuando se crea una cita."""
    await sio.emit("appointment_created", payload, to=_room_ap_day(coord_id, day), namespace=NAMESPACE)
    try:
        program_id = payload.get("program_id")
        await sio.emit("appointment_created", payload, to=_room_social_ap_day(day), namespace=NAMESPACE)
        if program_id:
            await sio.emit(
                "appointment_created",
                payload,
                to=_room_social_ap_day_prog(day, int(program_id)),
                namespace=NAMESPACE,
            )
    except Exception:
        logger.warning("Error broadcasting appointment_created to social rooms")


async def broadcast_drop_created(coord_id: int, payload: dict):
    """Broadcast cuando se crea una solicitud de baja."""
    await sio.emit("drop_created", payload, to=_room_drops(coord_id), namespace=NAMESPACE)


async def broadcast_request_status_changed(coord_id: int, payload: dict):
    """Broadcast cuando cambia el estado de una solicitud (cita o baja)."""
    day = payload.get("day")
    if day:
        await sio.emit("request_status_changed", payload, to=_room_ap_day(coord_id, day), namespace=NAMESPACE)
    await sio.emit("request_status_changed", payload, to=_room_drops(coord_id), namespace=NAMESPACE)
    try:
        if payload.get("type") == "APPOINTMENT" and day:
            program_id = payload.get("program_id")
            await sio.emit(
                "request_status_changed", payload, to=_room_social_ap_day(day), namespace=NAMESPACE
            )
            if program_id:
                await sio.emit(
                    "request_status_changed",
                    payload,
                    to=_room_social_ap_day_prog(day, int(program_id)),
                    namespace=NAMESPACE,
                )
    except Exception:
        logger.warning("Error broadcasting request_status_changed to social rooms")


# ==================== Event Registration ====================

def register_request_namespace(sio_server):
    """Registra los event handlers del namespace /requests."""

    @sio_server.on("connect", namespace=NAMESPACE)
    async def on_connect(sid, environ):
        user = current_user_from_environ(environ)
        if not user:
            return False
        await sio_server.save_session(sid, {"user": user}, namespace=NAMESPACE)
        await sio_server.emit("hello", {"msg": "WS /requests conectado"}, to=sid, namespace=NAMESPACE)

    @sio_server.on("disconnect", namespace=NAMESPACE)
    async def on_disconnect(sid):
        pass

    # -------- Appointments (por día) --------

    @sio_server.on("join_ap_day", namespace=NAMESPACE)
    async def on_join_ap_day(sid, data):
        try:
            coord_id = int((data or {}).get("coord_id") or 0)
            day = (data or {}).get("day") or ""
        except Exception:
            await sio_server.emit("error", {"error": "bad_payload"}, to=sid, namespace=NAMESPACE)
            return
        if coord_id <= 0 or not day:
            await sio_server.emit("error", {"error": "invalid_join_ap_day"}, to=sid, namespace=NAMESPACE)
            return
        await sio_server.enter_room(sid, _room_ap_day(coord_id, day), namespace=NAMESPACE)
        await sio_server.emit("joined_ap_day", {"coord_id": coord_id, "day": day}, to=sid, namespace=NAMESPACE)

    @sio_server.on("leave_ap_day", namespace=NAMESPACE)
    async def on_leave_ap_day(sid, data):
        try:
            coord_id = int((data or {}).get("coord_id") or 0)
            day = (data or {}).get("day") or ""
        except Exception:
            await sio_server.emit("error", {"error": "bad_payload"}, to=sid, namespace=NAMESPACE)
            return
        if coord_id <= 0 or not day:
            await sio_server.emit("error", {"error": "invalid_leave_ap_day"}, to=sid, namespace=NAMESPACE)
            return
        await sio_server.leave_room(sid, _room_ap_day(coord_id, day), namespace=NAMESPACE)
        await sio_server.emit("left_ap_day", {"coord_id": coord_id, "day": day}, to=sid, namespace=NAMESPACE)

    # -------- Drops (1 room por coordinador) --------

    @sio_server.on("join_drops", namespace=NAMESPACE)
    async def on_join_drops(sid, data):
        try:
            coord_id = int((data or {}).get("coord_id") or 0)
        except Exception:
            await sio_server.emit("error", {"error": "bad_payload"}, to=sid, namespace=NAMESPACE)
            return
        if coord_id <= 0:
            await sio_server.emit("error", {"error": "invalid_join_drops"}, to=sid, namespace=NAMESPACE)
            return
        await sio_server.enter_room(sid, _room_drops(coord_id), namespace=NAMESPACE)
        await sio_server.emit("joined_drops", {"coord_id": coord_id}, to=sid, namespace=NAMESPACE)

    # -------- Social rooms (estudiantes por día y programa) --------

    @sio_server.on("join_social_ap_day", namespace=NAMESPACE)
    async def on_join_social_ap_day(sid, data):
        day = (data or {}).get("day") or ""
        program_id = (data or {}).get("program_id")
        if not day:
            await sio_server.emit("error", {"error": "invalid_day"}, to=sid, namespace=NAMESPACE)
            return
        if program_id:
            try:
                pid = int(program_id)
            except Exception:
                await sio_server.emit("error", {"error": "invalid_program_id"}, to=sid, namespace=NAMESPACE)
                return
            await sio_server.enter_room(sid, _room_social_ap_day_prog(day, pid), namespace=NAMESPACE)
        else:
            await sio_server.enter_room(sid, _room_social_ap_day(day), namespace=NAMESPACE)
        await sio_server.emit(
            "joined_social_ap_day", {"day": day, "program_id": program_id}, to=sid, namespace=NAMESPACE
        )

    @sio_server.on("leave_social_ap_day", namespace=NAMESPACE)
    async def on_leave_social_ap_day(sid, data):
        day = (data or {}).get("day") or ""
        program_id = (data or {}).get("program_id")
        if not day:
            await sio_server.emit("error", {"error": "invalid_day"}, to=sid, namespace=NAMESPACE)
            return
        if program_id:
            try:
                pid = int(program_id)
            except Exception:
                await sio_server.emit("error", {"error": "invalid_program_id"}, to=sid, namespace=NAMESPACE)
                return
            await sio_server.leave_room(sid, _room_social_ap_day_prog(day, pid), namespace=NAMESPACE)
        else:
            await sio_server.leave_room(sid, _room_social_ap_day(day), namespace=NAMESPACE)
        await sio_server.emit(
            "left_social_ap_day", {"day": day, "program_id": program_id}, to=sid, namespace=NAMESPACE
        )
