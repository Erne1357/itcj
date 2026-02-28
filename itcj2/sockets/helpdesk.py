"""
WebSocket namespace /helpdesk para Helpdesk.

Migración de itcj/core/sockets/helpdesk.py (Flask-SocketIO sync)
a python-socketio ASGI (async nativo).

Broadcast functions: no reciben `socketio` como parámetro,
usan el `sio` global de .server directamente.
"""
import asyncio
import logging

from itcj.core.utils.socket_auth import current_user_from_environ

from .server import sio

logger = logging.getLogger("itcj2.sockets.helpdesk")

NAMESPACE = "/helpdesk"


# ==================== Room Helpers ====================

def _ticket_room(ticket_id: int) -> str:
    return f"ticket:{ticket_id}"


def _tech_room(user_id: int) -> str:
    return f"tech:{user_id}"


def _team_room(area: str) -> str:
    return f"team:{area}"


def _admin_room() -> str:
    return "admin:all"


def _dept_room(department_id: int) -> str:
    return f"dept:{department_id}"


# ==================== Async Broadcast Functions ====================

async def broadcast_ticket_created(ticket_data: dict):
    """Broadcast cuando se crea un ticket nuevo."""
    area = (ticket_data.get("area") or "").lower()
    department_id = ticket_data.get("department_id")

    if area in ("desarrollo", "soporte"):
        await sio.emit("ticket_created", ticket_data, to=_team_room(area), namespace=NAMESPACE)
    if department_id:
        await sio.emit("ticket_created", ticket_data, to=_dept_room(int(department_id)), namespace=NAMESPACE)
    await sio.emit("ticket_created", ticket_data, to=_admin_room(), namespace=NAMESPACE)


async def broadcast_ticket_assigned(
    ticket_id: int, assigned_to_id: int, area: str, payload: dict, department_id: int = None
):
    """Broadcast cuando se asigna un ticket a un técnico."""
    await sio.emit("ticket_assigned", payload, to=_tech_room(assigned_to_id), namespace=NAMESPACE)
    await sio.emit("ticket_assigned", payload, to=_ticket_room(ticket_id), namespace=NAMESPACE)
    area_lower = (area or "").lower()
    if area_lower in ("desarrollo", "soporte"):
        await sio.emit("ticket_assigned", payload, to=_team_room(area_lower), namespace=NAMESPACE)
    if department_id:
        await sio.emit("ticket_assigned", payload, to=_dept_room(int(department_id)), namespace=NAMESPACE)
    await sio.emit("ticket_assigned", payload, to=_admin_room(), namespace=NAMESPACE)


async def broadcast_ticket_reassigned(
    ticket_id: int,
    new_assigned_id: int,
    prev_assigned_id: int,
    area: str,
    payload: dict,
    department_id: int = None,
):
    """Broadcast cuando se reasigna un ticket."""
    await sio.emit("ticket_reassigned", payload, to=_tech_room(new_assigned_id), namespace=NAMESPACE)
    if prev_assigned_id:
        await sio.emit("ticket_reassigned", payload, to=_tech_room(prev_assigned_id), namespace=NAMESPACE)
    await sio.emit("ticket_reassigned", payload, to=_ticket_room(ticket_id), namespace=NAMESPACE)
    area_lower = (area or "").lower()
    if area_lower in ("desarrollo", "soporte"):
        await sio.emit("ticket_reassigned", payload, to=_team_room(area_lower), namespace=NAMESPACE)
    if department_id:
        await sio.emit("ticket_reassigned", payload, to=_dept_room(int(department_id)), namespace=NAMESPACE)
    await sio.emit("ticket_reassigned", payload, to=_admin_room(), namespace=NAMESPACE)


async def broadcast_ticket_status_changed(
    ticket_id: int, assignee_id: int, area: str, payload: dict, department_id: int = None
):
    """Broadcast cuando cambia el estado de un ticket."""
    await sio.emit("ticket_status_changed", payload, to=_ticket_room(ticket_id), namespace=NAMESPACE)
    if assignee_id:
        await sio.emit("ticket_status_changed", payload, to=_tech_room(assignee_id), namespace=NAMESPACE)
    area_lower = (area or "").lower()
    if area_lower in ("desarrollo", "soporte"):
        await sio.emit("ticket_status_changed", payload, to=_team_room(area_lower), namespace=NAMESPACE)
    if department_id:
        await sio.emit("ticket_status_changed", payload, to=_dept_room(int(department_id)), namespace=NAMESPACE)
    await sio.emit("ticket_status_changed", payload, to=_admin_room(), namespace=NAMESPACE)


async def broadcast_ticket_comment_added(ticket_id: int, payload: dict):
    """Broadcast cuando se agrega un comentario a un ticket."""
    await sio.emit("ticket_comment_added", payload, to=_ticket_room(ticket_id), namespace=NAMESPACE)


async def broadcast_ticket_self_assigned(ticket_id: int, area: str, payload: dict):
    """Broadcast cuando un técnico toma un ticket del pool del equipo."""
    area_lower = (area or "").lower()
    if area_lower in ("desarrollo", "soporte"):
        await sio.emit("ticket_self_assigned", payload, to=_team_room(area_lower), namespace=NAMESPACE)
    await sio.emit("ticket_self_assigned", payload, to=_ticket_room(ticket_id), namespace=NAMESPACE)
    await sio.emit("ticket_self_assigned", payload, to=_admin_room(), namespace=NAMESPACE)


# ==================== Event Registration ====================

def register_helpdesk_namespace(sio_server):
    """Registra los event handlers del namespace /helpdesk."""

    @sio_server.on("connect", namespace=NAMESPACE)
    async def on_connect(sid, environ):
        user = current_user_from_environ(environ)
        if not user:
            return False
        await sio_server.save_session(sid, {"user": user}, namespace=NAMESPACE)
        await sio_server.emit("hello", {"msg": "WS /helpdesk conectado"}, to=sid, namespace=NAMESPACE)

    @sio_server.on("disconnect", namespace=NAMESPACE)
    async def on_disconnect(sid):
        try:
            from itcj.core.extensions import db
            await asyncio.to_thread(db.session.remove)
        except Exception:
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

    # -------- Tech Dashboard Room --------

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

    # -------- Team Room --------

    @sio_server.on("join_team", namespace=NAMESPACE)
    async def on_join_team(sid, data):
        area = (data or {}).get("area", "").lower()
        if area not in ("desarrollo", "soporte"):
            await sio_server.emit("error", {"error": "invalid_area"}, to=sid, namespace=NAMESPACE)
            return
        await sio_server.enter_room(sid, _team_room(area), namespace=NAMESPACE)
        await sio_server.emit("joined_team", {"area": area}, to=sid, namespace=NAMESPACE)

    @sio_server.on("leave_team", namespace=NAMESPACE)
    async def on_leave_team(sid, data):
        area = (data or {}).get("area", "").lower()
        if area not in ("desarrollo", "soporte"):
            await sio_server.emit("error", {"error": "invalid_area"}, to=sid, namespace=NAMESPACE)
            return
        await sio_server.leave_room(sid, _team_room(area), namespace=NAMESPACE)
        await sio_server.emit("left_team", {"area": area}, to=sid, namespace=NAMESPACE)

    # -------- Admin Room --------

    @sio_server.on("join_admin", namespace=NAMESPACE)
    async def on_join_admin(sid, data=None):
        await sio_server.enter_room(sid, _admin_room(), namespace=NAMESPACE)
        await sio_server.emit("joined_admin", {}, to=sid, namespace=NAMESPACE)

    @sio_server.on("leave_admin", namespace=NAMESPACE)
    async def on_leave_admin(sid, data=None):
        await sio_server.leave_room(sid, _admin_room(), namespace=NAMESPACE)
        await sio_server.emit("left_admin", {}, to=sid, namespace=NAMESPACE)

    # -------- Department Room (para secretarias) --------

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
