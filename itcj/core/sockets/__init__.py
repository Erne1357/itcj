# sockets/__init__.py (refactorizado)
from flask_socketio import SocketIO
from flask import current_app, request, g
from itcj.core.utils.redis_conn import REDIS_URL, REDIS_HOST, REDIS_PORT
from itcj.core.utils.jwt_tools import decode_jwt
from itcj.core.extensions import db
import os

# Configuración de CORS basada en entorno
CORS_ORIGINS = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:8000",
    "http://127.0.0.1:8000"
] if os.getenv("FLASK_ENV") == "development" else os.getenv("DOMAIN").split(",")

def init_socketio(app):
    """Inicializa SocketIO y registra todos los eventos."""
    
    # Obtener URL de Redis
    redis_url = (
        os.getenv("SOCKET_IO_REDIS_URL")
        or REDIS_URL
        or f"redis://{REDIS_HOST}:{REDIS_PORT}/0"
    )
    
    # Crea la instancia de SocketIO dentro de la función
    # Esto asegura que cada worker de Gunicorn tenga su propia instancia.
    socketio = SocketIO(
        app, 
        async_mode="eventlet",
        message_queue=redis_url,
        cors_allowed_origins=CORS_ORIGINS,
        logger=True, 
        engineio_logger=True,
        ping_interval=25,
        ping_timeout=60,
        always_connect=False
    )
    
    app.logger.info(f"SocketIO inicializado con Redis: {redis_url}")
    
    # Registra aquí los eventos para esta instancia
    @socketio.on("connect")
    def handle_global_connect():
        try:
            token = request.cookies.get("itcj_token")
            if not token:
                current_app.logger.warning("WebSocket: No se encontró token")
                return False

            data = decode_jwt(token)
            if not data:
                current_app.logger.warning("WebSocket: Token inválido")
                return False

            g.current_user = data
            current_app.logger.info(f"WebSocket conectado: {data.get('cn', 'Usuario')}")
            return True

        except Exception as e:
            current_app.logger.exception(f"Error autenticando WebSocket: {e}")
            return False

    @socketio.on("disconnect")
    def handle_global_disconnect():
        try:
            if hasattr(g, 'current_user'):
                current_app.logger.info(f"WebSocket desconectado: {g.current_user.get('cn', 'Usuario')}")
            db.session.remove()
        except Exception:
            pass

    @socketio.on_error_default
    def handle_socketio_error(e):
        try:
            db.session.rollback()
            db.session.remove()
        except Exception:
            pass
        current_app.logger.exception("Error no controlado en Socket.IO")
    
    # Registro de eventos por namespace
    from .slots import register_slot_events
    from .requests import register_request_events
    from .notifications import register_notification_events
    
    register_slot_events(socketio)
    register_request_events(socketio)
    register_notification_events(socketio)

    return socketio