"""
Instancia global del AsyncServer de python-socketio.

Se importa desde los módulos de namespace para emitir eventos
sin crear imports circulares con itcj2/sockets/__init__.py.
"""
import socketio

from itcj2.config import get_settings


def _cors_origins() -> list[str]:
    settings = get_settings()
    if settings.FLASK_ENV == "development":
        return [
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:8001",
            "http://127.0.0.1:8001",
        ]
    if settings.CORS_ORIGINS:
        return [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
    return [
        "https://enlinea.cdjuarez.tecnm.mx",
        "https://siiapec.cdjuarez.tecnm.mx",
    ]


# F2.1 — En los workers HTTP (APP_ROLE=http) el manager es write_only: emiten
# publicando en Redis pero NO se suscriben al canal. Sin esto, los 4 workers
# escucharían cada mensaje de Socket.IO para intentar entregarlo a 0 clientes
# locales (nadie se conecta ahí: nginx manda /socket.io/ al contenedor
# `sockets`) — fanout x4 de todo el tráfico de sockets, para nada.
_WRITE_ONLY = get_settings().APP_ROLE == "http"

# AsyncServer — modo ASGI nativo, sin eventlet
# AsyncRedisManager usa el mismo protocolo Redis que Flask-SocketIO,
# por lo que mensajes emitidos desde Flask también llegan a los clientes.
sio = socketio.AsyncServer(
    async_mode="asgi",
    client_manager=socketio.AsyncRedisManager(
        get_settings().REDIS_URL, write_only=_WRITE_ONLY
    ),
    cors_allowed_origins=_cors_origins(),
    logger=False,
    engineio_logger=False,
)
