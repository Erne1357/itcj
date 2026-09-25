"""
WebSocket namespace /notify para notificaciones de usuario.

Desde core-config-revamp F6, /notify es además la FUENTE DE VERDAD de la
presencia de la plataforma (spec §3.5 / contrato C5): cada connect/disconnect
registra al usuario en Redis (presence_service, sorted-sets con timestamp,
poda en lectura) y dispara el broadcast `active_users` hacia el namespace
/system (canal broadcast-only que consume el widget de /itcj/config).

Desde la ronda 3 de observabilidad el shell manda además un LATIDO por este
mismo socket (`HEARTBEAT_EVENT`, ver más abajo) con la app que tiene abierta:
sin él la poda en lectura borraba a gente que seguía dentro, y no había ninguna
señal de en QUÉ app estaban.
"""
import logging

from itcj2.core.utils.socket_auth import current_user_from_environ

from .server import sio

logger = logging.getLogger("itcj2.sockets.notifications")

NAMESPACE = "/notify"
SYSTEM_NAMESPACE = "/system"

# Latido del shell (ronda 3 de observabilidad). Contrato con el cliente:
#   emit("presence_heartbeat", {"app": "<app_key>"}) al namespace /notify,
#   cada ~60 s, por el socket que YA está abierto (ninguna petición HTTP nueva).
# `app_key` es una de las 9 claves del vocabulario cerrado; el shell sin ninguna
# app abierta en el iframe manda "core". Sin payload, sin campo `app` o con una
# clave desconocida el servidor cuenta el latido como "otro": nunca lo descarta,
# porque el usuario SÍ está dentro y lo que se perdió es solo la dimensión app.
# No hay ack: el cliente no necesita respuesta y un ack por usuario y minuto es
# tráfico regalado.
HEARTBEAT_EVENT = "presence_heartbeat"


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

    @sio_server.on(HEARTBEAT_EVENT, namespace=NAMESPACE)
    async def on_presence_heartbeat(sid, data=None):
        """Refresca la presencia del usuario y la app que reporta (ver HEARTBEAT_EVENT).

        Sin este evento la marca del `connect` se salía de la ventana y la poda
        en lectura borraba a gente que seguía dentro (93,7 % del tiempo medido
        en producción). La identidad NO sale del payload: se lee de la sesión
        del socket, que la fijó el `connect` tras validar el JWT — un cliente no
        puede marcar presencia de otro uid ni marcar nada sin autenticarse.
        """
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
        reported = data.get("app") if isinstance(data, dict) else None
        previous_app = (session or {}).get("app")
        try:
            app_key = presence_service.touch(
                _redis(), uid, bucket, reported, previous_app
            )
        except Exception as exc:  # la presencia NUNCA tira el socket
            logger.warning("presence: heartbeat failed for uid=%s: %s", uid, exc)
            return
        if app_key != previous_app:
            await sio_server.save_session(
                sid, {**(session or {}), "app": app_key}, namespace=NAMESPACE
            )

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
        # La app del ÚLTIMO latido de este socket (None si nunca latió: shell
        # viejo sin el cliente de la ronda 3, o pestaña cerrada antes del
        # primer latido — en ese caso no hay marca de app que retirar).
        app_key = (session or {}).get("app")

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
                # El bucket sigue vivo por la otra pestaña, pero la app que
                # reportaba ESTE socket ya no está abierta en él (ver
                # mark_app_offline: la otra pestaña la re-afirma si la comparte).
                presence_service.mark_online(_redis(), uid, bucket)
                presence_service.mark_app_offline(_redis(), uid, app_key)
            else:
                presence_service.mark_offline(_redis(), uid, bucket, app_key)
        except Exception as exc:
            logger.warning("presence: mark_offline failed for uid=%s: %s", uid, exc)
        await _broadcast_active_users(sio_server)
