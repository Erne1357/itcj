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


# ==================== ACL Helpers ====================
# Los rooms de /requests reparten request_id, student_id, program_id y status de
# CADA solicitud del coordinador. Unirse tiene que exigir lo mismo que la API
# equivalente: api/coord/*.py deriva el coord_id de la sesión, nunca del cliente,
# y api/social.py exige agendatec.social.api.read.appointments.
#
# Sin esto, cualquier usuario autenticado podía emitir join_drops {coord_id: N}
# iterando N y ver en vivo el flujo completo de solicitudes del instituto.
#
# Corren en thread pool (asyncio.to_thread): abren su propia sesión sync, hacen
# una query por índice, y solo una vez por carga de página.

def _is_that_coordinator_sync(user: dict | None, coord_id: int) -> bool:
    """Solo el coordinador dueño del room (o un admin global) puede unirse."""
    if not user:
        return False
    if str(user.get("role")) == "admin":
        return True
    from itcj2.database import SessionLocal
    from itcj2.apps.agendatec.helpers import get_coordinator_id_for_user
    db = SessionLocal()
    try:
        return get_coordinator_id_for_user(int(user["sub"]), db) == coord_id
    except Exception:
        logger.exception("Fallo al resolver el coordinador para el ACL de /requests")
        return False
    finally:
        db.close()


def _can_read_social_sync(user: dict | None) -> bool:
    """Los rooms social:ap:* son de servicio social, no de alumnos."""
    if not user:
        return False
    if str(user.get("role")) == "admin":
        return True
    from itcj2.database import SessionLocal
    from itcj2.core.services.authz_cache import cached_has_assignment, cached_perms
    db = SessionLocal()
    try:
        uid = int(user["sub"])
        if not cached_has_assignment(db, uid, "agendatec"):
            return False
        return "agendatec.social.api.read.appointments" in cached_perms(db, uid, "agendatec")
    except Exception:
        logger.exception("Fallo al resolver permisos para el ACL social de /requests")
        return False
    finally:
        db.close()


# ==================== Event Registration ====================

def register_request_namespace(sio_server):
    """Registra los event handlers del namespace /requests."""

    @sio_server.on("connect", namespace=NAMESPACE)
    async def on_connect(sid, environ):
        user = current_user_from_environ(environ)
        if not user:
            return False
        # TEMP_TEST_GATE — lazy import evita circular
        from itcj2.apps.agendatec.helpers import TEMP_TEST_GATE_check_student_sync
        allowed = await asyncio.to_thread(TEMP_TEST_GATE_check_student_sync, user)
        if not allowed:
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
        sess = await sio_server.get_session(sid, namespace=NAMESPACE)
        if not await asyncio.to_thread(_is_that_coordinator_sync, (sess or {}).get("user"), coord_id):
            await sio_server.emit("error", {"error": "forbidden"}, to=sid, namespace=NAMESPACE)
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
        sess = await sio_server.get_session(sid, namespace=NAMESPACE)
        if not await asyncio.to_thread(_is_that_coordinator_sync, (sess or {}).get("user"), coord_id):
            await sio_server.emit("error", {"error": "forbidden"}, to=sid, namespace=NAMESPACE)
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
        sess = await sio_server.get_session(sid, namespace=NAMESPACE)
        if not await asyncio.to_thread(_can_read_social_sync, (sess or {}).get("user")):
            await sio_server.emit("error", {"error": "forbidden"}, to=sid, namespace=NAMESPACE)
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
