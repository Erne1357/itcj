"""
WebSocket namespace /maint para la app de Mantenimiento.

Mirrors itcj2/sockets/helpdesk.py — sin team rooms (maint no tiene split por área).
Rooms: ticket:{id}, tech:{user_id}, dispatcher:all, dept:{id}.
"""
import asyncio
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


async def broadcast_ticket_routed(coordinator_id: int, payload: dict):
    """Broadcast cuando se enruta/devuelve un ticket a la cola de un coordinador.

    Se emite a su room personal (tech:{coordinator_id}) para que el tablero de
    asignación refresque en vivo (M8). El aviso in-app va aparte por el canal
    de notificaciones del core (NotificationService)."""
    await sio.emit("ticket_routed", payload, to=_tech_room(coordinator_id), namespace=NAMESPACE)


async def broadcast_ticket_comment_added(ticket_id: int, payload: dict):
    """Broadcast cuando se agrega un comentario a un ticket."""
    await sio.emit("ticket_comment_added", payload, to=_ticket_room(ticket_id), namespace=NAMESPACE)


async def broadcast_ticket_rated(ticket_id: int, technician_ids: list, payload: dict):
    """Broadcast cuando el solicitante califica un ticket."""
    for tech_id in technician_ids:
        await sio.emit("ticket_rated", payload, to=_tech_room(tech_id), namespace=NAMESPACE)
    await sio.emit("ticket_rated", payload, to=_ticket_room(ticket_id), namespace=NAMESPACE)


# ==================== ACL Helpers (H10) ====================
# Validan rol/pertenencia/visibilidad antes de unir un socket a un room.
# Abren su propia sesión sync (ORM sync del proyecto); las queries son por PK/
# índice y los joins ocurren una vez por carga de página → costo despreciable.

def _user_maint_roles(db, user_id: int) -> set:
    from itcj2.core.services.authz_service import user_roles_in_app
    try:
        return set(user_roles_in_app(db, user_id, "maint"))
    except Exception:
        return set()


_FULL_ACCESS_MAINT = {"admin", "dispatcher",
                      "maint_area_coordinator", "maint_general_coordinator"}


def _can_join_dispatcher(user: dict | None) -> bool:
    """Solo dispatcher/admin pueden escuchar la bandeja global (dispatcher:all)."""
    if not user:
        return False
    if str(user.get("role")) == "admin":
        return True
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        roles = _user_maint_roles(db, int(user["sub"]))
        return bool(roles & {"dispatcher", "admin"})
    finally:
        db.close()


def _can_join_dept(user: dict | None, dept_id: int) -> bool:
    """Un usuario solo escucha el room de SU departamento; full-access ve todos."""
    if not user:
        return False
    if str(user.get("role")) == "admin":
        return True
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        uid = int(user["sub"])
        roles = _user_maint_roles(db, uid)
        if roles & _FULL_ACCESS_MAINT:
            return True
        from itcj2.apps.maint.services.department_dashboard_service import _resolve_user_departments
        dept_ids = {d["id"] for d in _resolve_user_departments(db, uid)}
        return dept_id in dept_ids
    finally:
        db.close()


def _can_join_ticket(user: dict | None, ticket_id: int) -> bool:
    """Reusa can_user_view_ticket: mismo scope que la API de detalle."""
    if not user:
        return False
    if str(user.get("role")) == "admin":
        return True
    from itcj2.database import SessionLocal
    db = SessionLocal()
    try:
        from itcj2.apps.maint.models.ticket import MaintTicket
        from itcj2.apps.maint.services.ticket_service import can_user_view_ticket
        ticket = db.get(MaintTicket, ticket_id)
        if not ticket:
            return False
        return can_user_view_ticket(db, ticket, int(user["sub"]))
    finally:
        db.close()


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
        # H10: validar visibilidad del ticket antes de unir al room.
        session = await sio_server.get_session(sid, namespace=NAMESPACE)
        user = (session or {}).get("user")
        if not await asyncio.to_thread(_can_join_ticket, user, ticket_id):
            await sio_server.emit("error", {"error": "forbidden"}, to=sid, namespace=NAMESPACE)
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
        # H10: solo dispatcher/admin escuchan la bandeja global.
        session = await sio_server.get_session(sid, namespace=NAMESPACE)
        user = (session or {}).get("user")
        if not await asyncio.to_thread(_can_join_dispatcher, user):
            await sio_server.emit("error", {"error": "forbidden"}, to=sid, namespace=NAMESPACE)
            return
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
        # H10: validar pertenencia al departamento (o rol full-access).
        session = await sio_server.get_session(sid, namespace=NAMESPACE)
        user = (session or {}).get("user")
        if not await asyncio.to_thread(_can_join_dept, user, dept_id):
            await sio_server.emit("error", {"error": "forbidden"}, to=sid, namespace=NAMESPACE)
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
