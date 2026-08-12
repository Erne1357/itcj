"""
Entry point ASGI para FastAPI + Socket.IO.

El proceso se comporta según ``APP_ROLE`` (itcj2/config.py), para poder correr
HTTP con varios workers uvicorn SIN romper Socket.IO (F2.1):

  APP_ROLE=all     (default — dev, tests, CLI)
      socketio.ASGIApp(sio, fastapi_app)
        ├── /socket.io/...  → AsyncServer (python-socketio)
        └── /*              → FastAPI

  APP_ROLE=http    (prod: backend-blue/green, `uvicorn --workers 4`)
      Solo FastAPI. NO monta /socket.io/: la sesión engine.io es estado en
      memoria del proceso y con N workers el polling cae en procesos distintos
      y truena. Los workers SIGUEN emitiendo eventos — `sio.emit` publica en
      Redis (AsyncRedisManager) y el proceso de sockets los entrega.

  APP_ROLE=socket  (prod: contenedor `sockets`, 1 worker)
      Igual que `all`. Es el único que sirve /socket.io/ y el único que
      retransmite el canal `task_events` de Celery (ver itcj2/main.py).

El reparto entre roles lo hace nginx por `location` (docker/nginx/nginx.prod.conf).
"""
import socketio

from itcj2.config import get_settings
from itcj2.main import create_app

_ROLE = get_settings().APP_ROLE

# App FastAPI (HTTP REST + páginas)
fastapi_app = create_app()

if _ROLE == "http":
    # Sin Socket.IO montado: /socket.io/ nunca llega aquí (nginx lo enruta al
    # contenedor `sockets`). Un hit directo devuelve 404, que es lo correcto.
    app = fastapi_app
else:
    from itcj2.sockets import sio  # También registra los namespaces al importar

    # ASGI combinado: SocketIO intercepta /socket.io/, el resto va a FastAPI
    app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)
