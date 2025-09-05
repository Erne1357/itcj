# sockets/__init__.py
from flask_socketio import SocketIO
from flask import current_app, request, g
from ..utils.redis_conn import REDIS_URL, REDIS_HOST, REDIS_PORT
from ..utils.jwt_tools import decode_jwt
from ...extensions import db
import os

# Configuración de Redis para SocketIO
REDIS_QUEUE_URL = (
    os.getenv("SOCKET_IO_REDIS_URL")
    or REDIS_URL
    or f"redis://{REDIS_HOST}:{REDIS_PORT}/0"
)

# CORS más específico para desarrollo
CORS_ORIGINS = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:8000",
    "http://127.0.0.1:8000"
] if os.getenv("FLASK_ENV") == "development" else ["https://tu-dominio.com"]

# Crear la instancia de SocketIO
socketio = SocketIO(
    async_mode="eventlet",
    cors_allowed_origins=CORS_ORIGINS,
    logger=True,  # Activar para debug
    engineio_logger=True,  # Activar para debug
    ping_interval=25,
    ping_timeout=60,
    always_connect=False  # Cambiar a False para rechazar conexiones inválidas
)

# Autenticación global
@socketio.on("connect")
def handle_global_connect(auth=None):
    """
    Autentica globalmente desde la cookie 'agendatec_token'.
    """
    try:
        # Obtener token desde cookies
        token = request.cookies.get("agendatec_token")
        if not token:
            current_app.logger.warning("WebSocket: No se encontró token")
            return False

        # Validar token
        data = decode_jwt(token)
        if not data:
            current_app.logger.warning("WebSocket: Token inválido")
            return False

        # Guardar usuario en el contexto
        g.current_user = data
        current_app.logger.info(f"WebSocket conectado: {data.get('cn', 'Usuario')}")
        return True

    except Exception as e:
        current_app.logger.exception(f"Error autenticando WebSocket: {e}")
        return False

@socketio.on("disconnect")
def handle_global_disconnect():
    """Limpieza global al desconectar"""
    try:
        if hasattr(g, 'current_user'):
            current_app.logger.info(f"WebSocket desconectado: {g.current_user.get('cn', 'Usuario')}")
        db.session.remove()
    except Exception:
        pass

@socketio.on_error_default
def handle_socketio_error(e):
    """Manejo global de errores"""
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

def init_socketio(app):
    """Inicializar SocketIO con la app Flask"""
    # Configurar Redis si está disponible
    redis_url = os.getenv("SOCKET_IO_REDIS_URL") or REDIS_QUEUE_URL
    try:
        socketio.init_app(
            app, 
            message_queue=redis_url,
            cors_allowed_origins=CORS_ORIGINS
        )
        app.logger.info(f"SocketIO inicializado con Redis: {redis_url}")
    except Exception as e:
        # Fallback sin Redis para desarrollo
        socketio.init_app(app, cors_allowed_origins=CORS_ORIGINS)
        app.logger.warning(f"SocketIO inicializado sin Redis: {e}")
    
    # Registrar eventos de cada namespace
    register_slot_events(socketio)
    register_request_events(socketio)
    register_notification_events(socketio)
    
    return socketio