"""
WebSocket namespace /notify para notificaciones de usuario.

Desde core-config-revamp F6, /notify es además la FUENTE DE VERDAD de la
presencia de la plataforma (spec §3.5 / contrato C5): cada connect/disconnect
registra al usuario en Redis (presence_service, sorted-sets con timestamp,
poda en lectura) y dispara el broadcast `active_users` hacia el namespace
/system (canal broadcast-only que consume el widget de /itcj/config).
"""
import logging

from itcj2.core.utils.socket_auth import current_user_from_environ

from .server import sio

logger = logging.getLogger("itcj2.sockets.notifications")

NAMESPACE = "/notify"
SYSTEM_NAMESPACE = "/system"


def _user_room(uid: int) -> str:
    return f"user:{uid}:notify"


def _redis():
    """UN cliente Redis por proceso (get_redis es singleton), no por evento."""
    from itcj2.core.utils.redis_conn import get_redis
    return get_redis()


async def _broadcast_active_users(sio_server) -> None:
    """Emite el conteo vigente a /system. Best-effort: Redis caído no rompe /notify."""
    from itcj2.core.services import presence_service
    try:
        counts = presence_service.get_counts(_redis())
    except Exception as exc:
        logger.warning("presence: get_counts failed: %s", exc)
        return
    await sio_server.emit("active_users", counts, namespace=SYSTEM_NAMESPACE)


# ==================== Async Broadcast Function ====================

async def push_notification(user_id: int, payload: dict):
    """Emite una notificación push a un usuario específico via WebSocket."""
    await sio.emit("notify", payload, to=_user_room(int(user_id)), namespace=NAMESPACE)


# ==================== Event Registration ====================

def register_notification_namespace(sio_server):
    """Registra los event handlers del namespace /notify."""

    @sio_server.on("connect", namespace=NAMESPACE)
    async def on_connect(sid, environ):
        from itcj2.core.services import presence_service

        user = current_user_from_environ(environ)
        if not user:
            return False
        uid = int(user["sub"])
        bucket = presence_service.bucket_for(user)
        await sio_server.save_session(
            sid, {"user": user, "bucket": bucket}, namespace=NAMESPACE
        )
        await sio_server.enter_room(sid, _user_room(uid), namespace=NAMESPACE)
        try:
            # Llamada sync corta a Redis local: patrón establecido en slots.py.
            presence_service.mark_online(_redis(), uid, bucket)
        except Exception as exc:  # la presencia NUNCA tira el handshake
            logger.warning("presence: mark_online failed for uid=%s: %s", uid, exc)
        await sio_server.emit(
            "hello",
            {"msg": "WS /notify conectado", "uid": uid},
            to=sid,
            namespace=NAMESPACE,
        )
        await _broadcast_active_users(sio_server)

    @sio_server.on("disconnect", namespace=NAMESPACE)
    async def on_disconnect(sid):
        from itcj2.core.services import presence_service

        try:
            session = await sio_server.get_session(sid, namespace=NAMESPACE)
        except Exception:
            session = None
        user = (session or {}).get("user")
        if not user:
            return
        uid = int(user["sub"])
        bucket = (session or {}).get("bucket") or presence_service.bucket_for(user)

        # Multi-pestaña: si el uid aún tiene OTRO socket vivo en /notify (otra
        # pestaña/iframe), refrescamos su timestamp en vez de sacarlo. En
        # python-socketio el sid saliente TODAVÍA figura en el room durante el
        # handler de disconnect, por eso se excluye explícitamente.
        # get_participants es la vista LOCAL del worker (deployment actual:
        # 1 worker uvicorn); en multi-worker la presencia se degrada a
        # aproximada y la ventana PRESENCE_WINDOW_SECONDS acota el error.
        has_other_socket = False
        try:
            for other_sid, _eio in sio_server.manager.get_participants(
                NAMESPACE, _user_room(uid)
            ):
                if other_sid != sid:
                    has_other_socket = True
                    break
        except Exception:
            has_other_socket = False
        try:
            if has_other_socket:
                presence_service.mark_online(_redis(), uid, bucket)
            else:
                presence_service.mark_offline(_redis(), uid, bucket)
        except Exception as exc:
            logger.warning("presence: mark_offline failed for uid=%s: %s", uid, exc)
        await _broadcast_active_users(sio_server)
