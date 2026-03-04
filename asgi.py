"""
Entry point ASGI para FastAPI + Socket.IO (Fase 3).

La estructura es:
  socketio.ASGIApp(sio, fastapi_app)
    │
    ├── /socket.io/...  → AsyncServer (python-socketio)
    └── /api/*          → FastAPI
"""
import socketio

from itcj2.main import create_app
from itcj2.sockets import sio  # También registra los 4 namespaces al importar

# App FastAPI (HTTP REST)
fastapi_app = create_app()

# ASGI combinado: SocketIO intercepta /socket.io/, el resto va a FastAPI
app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)
