from flask_socketio import SocketIO
from flask import current_app, request, g
from itcj.core.utils.redis_conn import REDIS_URL, REDIS_HOST, REDIS_PORT
from itcj.core.utils.jwt_tools import decode_jwt
from itcj.core.extensions import db
import os
import redis

# CORS - con credenciales NO se puede usar "*", hay que especificar orígenes
def get_cors_origins():
    if os.getenv("FLASK_ENV") == "development":
        return [
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "http://localhost:8000",
            "http://127.0.0.1:8000"
        ]
    # Producción: leer de variable de entorno o usar dominio por defecto
    cors_env = os.getenv("CORS_ORIGINS", "")
    if cors_env:
        return [origin.strip() for origin in cors_env.split(",")]
    # Fallback: dominios conocidos de producción
    return [
        "https://enlinea.cdjuarez.tecnm.mx",
        "https://siiapec.cdjuarez.tecnm.mx"
    ]

CORS_ORIGINS = get_cors_origins()

def init_socketio(app):
    """Inicializa SocketIO con Redis message_queue."""
    
    redis_url = os.getenv("REDIS_URL") or REDIS_URL or f"redis://{REDIS_HOST}:{REDIS_PORT}/0"
    
    # Verificar Redis
    try:
        r = redis.from_url(redis_url)
        r.ping()
        app.logger.info(f"✓ Redis conectado: {redis_url}")
    except Exception as e:
        app.logger.error(f"✗ Redis ERROR: {e}")
        raise
    
    # ⭐ Configuración simple y funcional
    socketio = SocketIO(
        app, 
        async_mode="eventlet",
        message_queue=redis_url,
        cors_allowed_origins=CORS_ORIGINS,
        logger=False,
        engineio_logger=False
    )

    app.logger.info("✓ SocketIO inicializado")

    @socketio.on("connect")
    def handle_global_connect():
        try:
            token = request.cookies.get("itcj_token")
            if not token:
                return False
            
            data = decode_jwt(token)
            if not data:
                return False
            
            g.current_user = data
            current_app.logger.info(f"WS conectado: {data.get('cn')} (SID: {request.sid})")
            return True
        except Exception as e:
            current_app.logger.error(f"WS connect error: {e}")
            return False

    @socketio.on("disconnect")
    def handle_global_disconnect():
        try:
            if hasattr(g, 'current_user'):
                current_app.logger.info(f"WS desconectado: {g.current_user.get('cn')}")
            db.session.remove()
        except:
            pass

    @socketio.on_error_default
    def handle_socketio_error(e):
        try:
            db.session.rollback()
            db.session.remove()
        except:
            pass
        current_app.logger.error(f"WS error: {e}")
    
    from .slots import register_slot_events
    from .requests import register_request_events
    from .notifications import register_notification_events
    
    register_slot_events(socketio)
    register_request_events(socketio)
    register_notification_events(socketio)

    return socketio