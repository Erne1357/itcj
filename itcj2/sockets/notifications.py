"""
WebSocket namespace /notify para notificaciones de usuario.

Migración de itcj/core/sockets/notifications.py (Flask-SocketIO sync)
a python-socketio ASGI (async nativo).
"""
import asyncio
import logging

from itcj.core.utils.socket_auth import current_user_from_environ

from .server import sio

logger = logging.getLogger("itcj2.sockets.notifications")

NAMESPACE = "/notify"


def _user_room(uid: int) -> str:
    return f"user:{uid}:notify"


# ==================== Async Broadcast Function ====================

async def push_notification(user_id: int, payload: dict):
    """Emite una notificación push a un usuario específico via WebSocket."""
    await sio.emit("notify", payload, to=_user_room(int(user_id)), namespace=NAMESPACE)


# ==================== Event Registration ====================

def register_notification_namespace(sio_server):
    """Registra los event handlers del namespace /notify."""

    @sio_server.on("connect", namespace=NAMESPACE)
    async def on_connect(sid, environ):
        user = current_user_from_environ(environ)
        if not user:
            return False
        uid = int(user["sub"])
        await sio_server.save_session(sid, {"user": user}, namespace=NAMESPACE)
        await sio_server.enter_room(sid, _user_room(uid), namespace=NAMESPACE)
        await sio_server.emit(
            "hello",
            {"msg": "WS /notify conectado", "uid": uid},
            to=sid,
            namespace=NAMESPACE,
        )

    @sio_server.on("disconnect", namespace=NAMESPACE)
    async def on_disconnect(sid):
        try:
            from itcj.core.extensions import db
            await asyncio.to_thread(db.session.remove)
        except Exception:
            pass
