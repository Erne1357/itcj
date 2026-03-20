"""
Socket.IO ASGI — Fase 3 de migración Flask → FastAPI.

Usa python-socketio con AsyncRedisManager, compatible con el protocolo
Redis de Flask-SocketIO, por lo que eventos emitidos desde Flask
llegan a los clientes conectados a este servidor.
"""
import socketio

from .server import sio  # noqa: F401 (re-export para asgi.py)

# ASGI app del servidor Socket.IO (se envuelve en asgi.py junto a FastAPI)
socket_app = socketio.ASGIApp(sio, socketio_path="socket.io")

# Registrar los 4 namespaces
from .helpdesk import register_helpdesk_namespace          # noqa: E402
from .notifications import register_notification_namespace  # noqa: E402
from .requests import register_request_namespace            # noqa: E402
from .slots import register_slot_namespace                  # noqa: E402
from .system import register_system_namespace               # noqa: E402

register_helpdesk_namespace(sio)
register_notification_namespace(sio)
register_request_namespace(sio)
register_slot_namespace(sio)
register_system_namespace(sio)
