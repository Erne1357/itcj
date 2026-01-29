# sockets/helpdesk.py
"""
WebSocket namespace para Helpdesk.

Proporciona eventos en tiempo real para:
- Cambios de estado de tickets
- Nuevas asignaciones
- Comentarios
- Actualizaciones de dashboard
"""
from flask import g, request, current_app
from flask_socketio import emit, join_room, leave_room
from itcj.core.utils.socket_auth import current_user_from_environ
from itcj.core.extensions import db

NAMESPACE = "/helpdesk"


# ==================== Room Helpers ====================

def _ticket_room(ticket_id: int) -> str:
    """Room para un ticket específico (detalle del ticket)."""
    return f"ticket:{ticket_id}"


def _tech_room(user_id: int) -> str:
    """Room personal del técnico (su dashboard)."""
    return f"tech:{user_id}"


def _team_room(area: str) -> str:
    """Room del equipo (desarrollo/soporte)."""
    return f"team:{area}"


def _admin_room() -> str:
    """Room para admin (todos los tickets)."""
    return "admin:all"


def _dept_room(department_id: int) -> str:
    """Room para secretaria de un departamento específico."""
    return f"dept:{department_id}"


# ==================== Event Registration ====================

def register_helpdesk_events(socketio):
    """Registra los eventos del namespace /helpdesk."""

    @socketio.on("connect", namespace=NAMESPACE)
    def on_connect():
        user = current_user_from_environ(request.environ)
        if not user:
            return False
        g.current_user = user
        emit("hello", {"msg": "WS /helpdesk conectado"})

    @socketio.on("disconnect", namespace=NAMESPACE)
    def on_disconnect(*args, **kwargs):
        try:
            db.session.remove()
        except Exception:
            pass

    # -------- Ticket Detail Room --------
    @socketio.on("join_ticket", namespace=NAMESPACE)
    def on_join_ticket(data):
        """Unirse al room de un ticket específico."""
        try:
            ticket_id = int((data or {}).get("ticket_id") or 0)
        except Exception:
            emit("error", {"error": "bad_payload"})
            return
        if ticket_id <= 0:
            emit("error", {"error": "invalid_ticket_id"})
            return
        join_room(_ticket_room(ticket_id))
        emit("joined_ticket", {"ticket_id": ticket_id})

    @socketio.on("leave_ticket", namespace=NAMESPACE)
    def on_leave_ticket(data):
        """Salir del room de un ticket específico."""
        try:
            ticket_id = int((data or {}).get("ticket_id") or 0)
        except Exception:
            emit("error", {"error": "bad_payload"})
            return
        if ticket_id <= 0:
            emit("error", {"error": "invalid_ticket_id"})
            return
        leave_room(_ticket_room(ticket_id))
        emit("left_ticket", {"ticket_id": ticket_id})

    # -------- Tech Dashboard Room --------
    @socketio.on("join_tech", namespace=NAMESPACE)
    def on_join_tech(data=None):
        """Unirse al room personal del técnico."""
        if not hasattr(g, 'current_user') or not g.current_user:
            emit("error", {"error": "not_authenticated"})
            return
        user_id = g.current_user.get("sub")
        if not user_id:
            emit("error", {"error": "invalid_user"})
            return
        join_room(_tech_room(int(user_id)))
        emit("joined_tech", {"user_id": user_id})

    @socketio.on("leave_tech", namespace=NAMESPACE)
    def on_leave_tech(data=None):
        """Salir del room personal del técnico."""
        if not hasattr(g, 'current_user') or not g.current_user:
            return
        user_id = g.current_user.get("sub")
        if user_id:
            leave_room(_tech_room(int(user_id)))
            emit("left_tech", {"user_id": user_id})

    # -------- Team Room --------
    @socketio.on("join_team", namespace=NAMESPACE)
    def on_join_team(data):
        """Unirse al room del equipo (desarrollo/soporte)."""
        area = (data or {}).get("area", "").lower()
        if area not in ["desarrollo", "soporte"]:
            emit("error", {"error": "invalid_area"})
            return
        join_room(_team_room(area))
        emit("joined_team", {"area": area})

    @socketio.on("leave_team", namespace=NAMESPACE)
    def on_leave_team(data):
        """Salir del room del equipo."""
        area = (data or {}).get("area", "").lower()
        if area not in ["desarrollo", "soporte"]:
            emit("error", {"error": "invalid_area"})
            return
        leave_room(_team_room(area))
        emit("left_team", {"area": area})

    # -------- Admin Room --------
    @socketio.on("join_admin", namespace=NAMESPACE)
    def on_join_admin(data=None):
        """Unirse al room de admin (todos los tickets)."""
        join_room(_admin_room())
        emit("joined_admin", {})

    @socketio.on("leave_admin", namespace=NAMESPACE)
    def on_leave_admin(data=None):
        """Salir del room de admin."""
        leave_room(_admin_room())
        emit("left_admin", {})

    # -------- Department Room (para secretarias) --------
    @socketio.on("join_dept", namespace=NAMESPACE)
    def on_join_dept(data):
        """Unirse al room de un departamento específico."""
        try:
            dept_id = int((data or {}).get("department_id") or 0)
        except Exception:
            emit("error", {"error": "bad_payload"})
            return
        if dept_id <= 0:
            emit("error", {"error": "invalid_department_id"})
            return
        join_room(_dept_room(dept_id))
        emit("joined_dept", {"department_id": dept_id})

    @socketio.on("leave_dept", namespace=NAMESPACE)
    def on_leave_dept(data):
        """Salir del room de un departamento."""
        try:
            dept_id = int((data or {}).get("department_id") or 0)
        except Exception:
            emit("error", {"error": "bad_payload"})
            return
        if dept_id <= 0:
            emit("error", {"error": "invalid_department_id"})
            return
        leave_room(_dept_room(dept_id))
        emit("left_dept", {"department_id": dept_id})


# ==================== Broadcast Functions ====================

def broadcast_ticket_created(socketio, ticket_data: dict):
    """
    Broadcast cuando se crea un ticket nuevo.

    Args:
        socketio: Instancia de SocketIO
        ticket_data: {id, ticket_number, title, area, priority, status, requester, department_id}
    """
    area = (ticket_data.get("area") or "").lower()
    department_id = ticket_data.get("department_id")

    # Notificar al room del equipo correspondiente
    if area in ["desarrollo", "soporte"]:
        socketio.emit("ticket_created", ticket_data,
                      to=_team_room(area), namespace=NAMESPACE)

    # Notificar al departamento específico (para secretarias)
    if department_id:
        socketio.emit("ticket_created", ticket_data,
                      to=_dept_room(int(department_id)), namespace=NAMESPACE)

    # Notificar a admin (centro de cómputo)
    socketio.emit("ticket_created", ticket_data,
                  to=_admin_room(), namespace=NAMESPACE)


def broadcast_ticket_assigned(socketio, ticket_id: int, assigned_to_id: int,
                              area: str, payload: dict, department_id: int = None):
    """
    Broadcast cuando se asigna un ticket a un técnico.

    Args:
        socketio: Instancia de SocketIO
        ticket_id: ID del ticket
        assigned_to_id: ID del usuario asignado
        area: Área del ticket (desarrollo/soporte)
        payload: Datos adicionales del evento
        department_id: ID del departamento del ticket (opcional)
    """
    # Notificar al técnico asignado
    socketio.emit("ticket_assigned", payload,
                  to=_tech_room(assigned_to_id), namespace=NAMESPACE)

    # Notificar al room del ticket
    socketio.emit("ticket_assigned", payload,
                  to=_ticket_room(ticket_id), namespace=NAMESPACE)

    # Notificar al equipo (el ticket sale del pool)
    area_lower = (area or "").lower()
    if area_lower in ["desarrollo", "soporte"]:
        socketio.emit("ticket_assigned", payload,
                      to=_team_room(area_lower), namespace=NAMESPACE)

    # Notificar al departamento específico (para secretarias)
    if department_id:
        socketio.emit("ticket_assigned", payload,
                      to=_dept_room(int(department_id)), namespace=NAMESPACE)

    # Notificar a admin
    socketio.emit("ticket_assigned", payload,
                  to=_admin_room(), namespace=NAMESPACE)


def broadcast_ticket_reassigned(socketio, ticket_id: int, new_assigned_id: int,
                                prev_assigned_id: int, payload: dict):
    """
    Broadcast cuando se reasigna un ticket.

    Args:
        socketio: Instancia de SocketIO
        ticket_id: ID del ticket
        new_assigned_id: ID del nuevo técnico asignado
        prev_assigned_id: ID del técnico anterior
        payload: Datos adicionales del evento
    """
    # Notificar al nuevo técnico
    socketio.emit("ticket_reassigned", payload,
                  to=_tech_room(new_assigned_id), namespace=NAMESPACE)

    # Notificar al técnico anterior
    if prev_assigned_id:
        socketio.emit("ticket_reassigned", payload,
                      to=_tech_room(prev_assigned_id), namespace=NAMESPACE)

    # Notificar al room del ticket
    socketio.emit("ticket_reassigned", payload,
                  to=_ticket_room(ticket_id), namespace=NAMESPACE)


def broadcast_ticket_status_changed(socketio, ticket_id: int, assignee_id: int,
                                    area: str, payload: dict, department_id: int = None):
    """
    Broadcast cuando cambia el estado de un ticket.

    Args:
        socketio: Instancia de SocketIO
        ticket_id: ID del ticket
        assignee_id: ID del técnico asignado (puede ser None)
        area: Área del ticket
        payload: {ticket_id, old_status, new_status, changed_by}
        department_id: ID del departamento del ticket (opcional)
    """
    # Notificar al room del ticket
    socketio.emit("ticket_status_changed", payload,
                  to=_ticket_room(ticket_id), namespace=NAMESPACE)

    # Notificar al técnico asignado
    if assignee_id:
        socketio.emit("ticket_status_changed", payload,
                      to=_tech_room(assignee_id), namespace=NAMESPACE)

    # Notificar al equipo
    area_lower = (area or "").lower()
    if area_lower in ["desarrollo", "soporte"]:
        socketio.emit("ticket_status_changed", payload,
                      to=_team_room(area_lower), namespace=NAMESPACE)

    # Notificar al departamento específico (para secretarias)
    if department_id:
        socketio.emit("ticket_status_changed", payload,
                      to=_dept_room(int(department_id)), namespace=NAMESPACE)

    # Notificar a admin
    socketio.emit("ticket_status_changed", payload,
                  to=_admin_room(), namespace=NAMESPACE)


def broadcast_ticket_comment_added(socketio, ticket_id: int, payload: dict):
    """
    Broadcast cuando se agrega un comentario a un ticket.

    Args:
        socketio: Instancia de SocketIO
        ticket_id: ID del ticket
        payload: {ticket_id, comment_id, author, is_internal, preview}
    """
    socketio.emit("ticket_comment_added", payload,
                  to=_ticket_room(ticket_id), namespace=NAMESPACE)


def broadcast_ticket_self_assigned(socketio, ticket_id: int, area: str, payload: dict):
    """
    Broadcast cuando un técnico toma un ticket del pool del equipo.

    Args:
        socketio: Instancia de SocketIO
        ticket_id: ID del ticket
        area: Área del ticket
        payload: {ticket_id, technician_id, technician_name}
    """
    # Notificar al equipo (el ticket sale del pool)
    area_lower = (area or "").lower()
    if area_lower in ["desarrollo", "soporte"]:
        socketio.emit("ticket_self_assigned", payload,
                      to=_team_room(area_lower), namespace=NAMESPACE)

    # Notificar al room del ticket
    socketio.emit("ticket_self_assigned", payload,
                  to=_ticket_room(ticket_id), namespace=NAMESPACE)

    # Notificar a admin
    socketio.emit("ticket_self_assigned", payload,
                  to=_admin_room(), namespace=NAMESPACE)
