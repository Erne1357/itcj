"""
WebSocket namespace /maint para la app de Mantenimiento.

Mirrors itcj2/sockets/helpdesk.py — sin team rooms (maint no tiene split por área).
Rooms: ticket:{id}, tech:{user_id}, dispatcher:all, dept:{id}.
"""
import logging

from itcj2.core.utils.socket_auth import current_user_from_environ

from .server import sio

logger = logging.getLogger("itcj2.sockets.maint")

NAMESPACE = "/maint"


# ==================== Room Helpers ====================

def _ticket_room(ticket_id: int) -> str:
    return f"ticket:{ticket_id}"


def _tech_room(user_id: int) -> str:
    return f"tech:{user_id}"


def _dispatcher_room() -> str:
    return "dispatcher:all"


def _dept_room(department_id: int) -> str:
    return f"dept:{department_id}"


# ==================== Async Broadcast Functions ====================

async def broadcast_ticket_created(ticket_data: dict):
    """Broadcast cuando se crea un ticket nuevo."""
    department_id = ticket_data.get("department_id")

    await sio.emit("ticket_created", ticket_data, to=_dispatcher_room(), namespace=NAMESPACE)
    if department_id:
        await sio.emit("ticket_created", ticket_data, to=_dept_room(int(department_id)), namespace=NAMESPACE)


async def broadcast_ticket_assigned(
    ticket_id: int,
    technician_ids: list,
    payload: dict,
    department_id: int = None,
):
    """Broadcast cuando se asigna uno o varios técnicos a un ticket."""
    for tech_id in technician_ids:
        await sio.emit("ticket_assigned", payload, to=_tech_room(tech_id), namespace=NAMESPACE)
    await sio.emit("ticket_assigned", payload, to=_ticket_room(ticket_id), namespace=NAMESPACE)
    await sio.emit("ticket_assigned", payload, to=_dispatcher_room(), namespace=NAMESPACE)
    if department_id:
        await sio.emit("ticket_assigned", payload, to=_dept_room(int(department_id)), namespace=NAMESPACE)


async def broadcast_ticket_unassigned(
    ticket_id: int,
    technician_id: int,
    payload: dict,
    department_id: int = None,
):
    """Broadcast cuando se remueve un técnico de un ticket."""
    await sio.emit("ticket_unassigned", payload, to=_tech_room(technician_id), namespace=NAMESPACE)
    await sio.emit("ticket_unassigned", payload, to=_ticket_room(ticket_id), namespace=NAMESPACE)
    await sio.emit("ticket_unassigned", payload, to=_dispatcher_room(), namespace=NAMESPACE)


async def broadcast_ticket_status_changed(
    ticket_id: int,
    technician_ids: list,
    payload: dict,
    department_id: int = None,
):
    """Broadcast cuando cambia el estado de un ticket."""
    for tech_id in technician_ids:
        await sio.emit("ticket_status_changed", payload, to=_tech_room(tech_id), namespace=NAMESPACE)
    await sio.emit("ticket_status_changed", payload, to=_ticket_room(ticket_id), namespace=NAMESPACE)
    await sio.emit("ticket_status_changed", payload, to=_dispatcher_room(), namespace=NAMESPACE)
    if department_id:
        await sio.emit("ticket_status_changed", payload, to=_dept_room(int(department_id)), namespace=NAMESPACE)


async def broadcast_ticket_resolved(
    ticket_id: int,
    requester_id: int,
    payload: dict,
    department_id: int = None,
):
    """Broadcast cuando se resuelve un ticket. Notifica al solicitante (via tech room como room personal)."""
    await sio.emit("ticket_resolved", payload, to=_tech_room(requester_id), namespace=NAMESPACE)
    await sio.emit("ticket_resolved", payload, to=_ticket_room(ticket_id), namespace=NAMESPACE)
    await sio.emit("ticket_resolved", payload, to=_dispatcher_room(), namespace=NAMESPACE)
    if department_id:
        await sio.emit("ticket_resolved", payload, to=_dept_room(int(department_id)), namespace=NAMESPACE)


async def broadcast_ticket_canceled(
    ticket_id: int,
    technician_ids: list,
    payload: dict,
    department_id: int = None,
):
    """Broadcast cuando se cancela un ticket."""
    for tech_id in technician_ids:
        await sio.emit("ticket_canceled", payload, to=_tech_room(tech_id), namespace=NAMESPACE)
    await sio.emit("ticket_canceled", payload, to=_ticket_room(ticket_id), namespace=NAMESPACE)
    await sio.emit("ticket_canceled", payload, to=_dispatcher_room(), namespace=NAMESPACE)
    if department_id:
        await sio.emit("ticket_canceled", payload, to=_dept_room(int(department_id)), namespace=NAMESPACE)


async def broadcast_ticket_comment_added(ticket_id: int, payload: dict):
    """Broadcast cuando se agrega un comentario a un ticket."""
    await sio.emit("ticket_comment_added", payload, to=_ticket_room(ticket_id), namespace=NAMESPACE)


async def broadcast_ticket_rated(ticket_id: int, technician_ids: list, payload: dict):
    """Broadcast cuando el solicitante califica un ticket."""
    for tech_id in technician_ids:
        await sio.emit("ticket_rated", payload, to=_tech_room(tech_id), namespace=NAMESPACE)
    await sio.emit("ticket_rated", payload, to=_ticket_room(ticket_id), namespace=NAMESPACE)


# ==================== Event Registration ====================

def register_maint_namespace(sio_server):
    """Registra los event handlers del namespace /maint."""

    @sio_server.on("connect", namespace=NAMESPACE)
    async def on_connect(sid, environ):
        user = current_user_from_environ(environ)
        if not user:
            return False
        await sio_server.save_session(sid, {"user": user}, namespace=NAMESPACE)
        await sio_server.emit("hello", {"msg": "WS /maint conectado"}, to=sid, namespace=NAMESPACE)

    @sio_server.on("disconnect", namespace=NAMESPACE)
    async def on_disconnect(sid):
        pass

    # -------- Ticket Detail Room --------

    @sio_server.on("join_ticket", namespace=NAMESPACE)
    async def on_join_ticket(sid, data):
        try:
            ticket_id = int((data or {}).get("ticket_id") or 0)
        except Exception:
            await sio_server.emit("error", {"error": "bad_payload"}, to=sid, namespace=NAMESPACE)
            return
        if ticket_id <= 0:
            await sio_server.emit("error", {"error": "invalid_ticket_id"}, to=sid, namespace=NAMESPACE)
            return
        await sio_server.enter_room(sid, _ticket_room(ticket_id), namespace=NAMESPACE)
        await sio_server.emit("joined_ticket", {"ticket_id": ticket_id}, to=sid, namespace=NAMESPACE)

    @sio_server.on("leave_ticket", namespace=NAMESPACE)
    async def on_leave_ticket(sid, data):
        try:
            ticket_id = int((data or {}).get("ticket_id") or 0)
        except Exception:
            await sio_server.emit("error", {"error": "bad_payload"}, to=sid, namespace=NAMESPACE)
            return
        if ticket_id <= 0:
            await sio_server.emit("error", {"error": "invalid_ticket_id"}, to=sid, namespace=NAMESPACE)
            return
        await sio_server.leave_room(sid, _ticket_room(ticket_id), namespace=NAMESPACE)
        await sio_server.emit("left_ticket", {"ticket_id": ticket_id}, to=sid, namespace=NAMESPACE)

    # -------- Tech Personal Room --------

    @sio_server.on("join_tech", namespace=NAMESPACE)
    async def on_join_tech(sid, data=None):
        session = await sio_server.get_session(sid, namespace=NAMESPACE)
        user = (session or {}).get("user")
        if not user:
            await sio_server.emit("error", {"error": "not_authenticated"}, to=sid, namespace=NAMESPACE)
            return
        user_id = user.get("sub")
        if not user_id:
            await sio_server.emit("error", {"error": "invalid_user"}, to=sid, namespace=NAMESPACE)
            return
        await sio_server.enter_room(sid, _tech_room(int(user_id)), namespace=NAMESPACE)
        await sio_server.emit("joined_tech", {"user_id": user_id}, to=sid, namespace=NAMESPACE)

    @sio_server.on("leave_tech", namespace=NAMESPACE)
    async def on_leave_tech(sid, data=None):
        session = await sio_server.get_session(sid, namespace=NAMESPACE)
        user = (session or {}).get("user")
        if not user:
            return
        user_id = user.get("sub")
        if user_id:
            await sio_server.leave_room(sid, _tech_room(int(user_id)), namespace=NAMESPACE)
            await sio_server.emit("left_tech", {"user_id": user_id}, to=sid, namespace=NAMESPACE)

    # -------- Dispatcher Room --------

    @sio_server.on("join_dispatcher", namespace=NAMESPACE)
    async def on_join_dispatcher(sid, data=None):
        await sio_server.enter_room(sid, _dispatcher_room(), namespace=NAMESPACE)
        await sio_server.emit("joined_dispatcher", {}, to=sid, namespace=NAMESPACE)

    @sio_server.on("leave_dispatcher", namespace=NAMESPACE)
    async def on_leave_dispatcher(sid, data=None):
        await sio_server.leave_room(sid, _dispatcher_room(), namespace=NAMESPACE)
        await sio_server.emit("left_dispatcher", {}, to=sid, namespace=NAMESPACE)

    # -------- Department Room --------

    @sio_server.on("join_dept", namespace=NAMESPACE)
    async def on_join_dept(sid, data):
        try:
            dept_id = int((data or {}).get("department_id") or 0)
        except Exception:
            await sio_server.emit("error", {"error": "bad_payload"}, to=sid, namespace=NAMESPACE)
            return
        if dept_id <= 0:
            await sio_server.emit("error", {"error": "invalid_department_id"}, to=sid, namespace=NAMESPACE)
            return
        await sio_server.enter_room(sid, _dept_room(dept_id), namespace=NAMESPACE)
        await sio_server.emit("joined_dept", {"department_id": dept_id}, to=sid, namespace=NAMESPACE)

    @sio_server.on("leave_dept", namespace=NAMESPACE)
    async def on_leave_dept(sid, data):
        try:
            dept_id = int((data or {}).get("department_id") or 0)
        except Exception:
            await sio_server.emit("error", {"error": "bad_payload"}, to=sid, namespace=NAMESPACE)
            return
        if dept_id <= 0:
            await sio_server.emit("error", {"error": "invalid_department_id"}, to=sid, namespace=NAMESPACE)
            return
        await sio_server.leave_room(sid, _dept_room(dept_id), namespace=NAMESPACE)
        await sio_server.emit("left_dept", {"department_id": dept_id}, to=sid, namespace=NAMESPACE)
