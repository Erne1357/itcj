"""
WebSocket namespace /system — canal BROADCAST-ONLY del conteo de usuarios activos.

Desde core-config-revamp F6 la fuente de verdad de presencia vive en /notify
(itcj2/sockets/notifications.py + presence_service, spec §3.5): sus hooks de
connect/disconnect son quienes emiten `active_users` hacia este namespace.
Aquí solo queda:
  1. autenticar el handshake (rechaza anónimos, igual que /notify), y
  2. al conectar, mandar el conteo vigente al sid entrante (snapshot inicial).

LEGACY ELIMINADO (2026-07): los sets `socket:active:students`,
`socket:active:admins` y `socket:user_sids:<uid>` ya NO se escriben ni leen.
Limpieza one-off por entorno (los user_sids expiran solos por su TTL de 24h):

    redis-cli DEL socket:active:students socket:active:admins
"""
import logging

from itcj2.core.utils.socket_auth import current_user_from_environ

logger = logging.getLogger("itcj2.sockets.system")

NAMESPACE = "/system"


def register_system_namespace(sio_server):
    """Registra los event handlers del namespace /system."""

    @sio_server.on("connect", namespace=NAMESPACE)
    async def on_connect(sid, environ):
        user = current_user_from_environ(environ)
        if not user:
            # Rechazar handshakes anónimos: evita que un cliente sin sesión
            # reciba los broadcasts de active_users.
            return False

        from itcj2.core.services import presence_service
        from itcj2.core.utils.redis_conn import get_redis

        try:
            counts = presence_service.get_counts(get_redis())
        except Exception as exc:
            # Conectado pero sin snapshot: el próximo broadcast lo actualiza.
            logger.warning("system: get_counts failed on connect: %s", exc)
            return

        await sio_server.emit("active_users", counts, to=sid, namespace=NAMESPACE)
