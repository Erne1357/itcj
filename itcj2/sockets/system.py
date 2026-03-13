"""
WebSocket namespace /system para monitoreo de usuarios activos y stats.

Maneja conteo de usuarios en linea basandose en conexiones activas.
Usa Redis para mantener estado compartido entre workers.
"""
import logging
import asyncio
import redis.asyncio as aioredis

from itcj2.config import get_settings
from itcj2.core.utils.socket_auth import current_user_from_environ
from .server import sio

logger = logging.getLogger("itcj2.sockets.system")

NAMESPACE = "/system"

# Claves Redis
KEY_USER_SIDS = "socket:user_sids:{uid}"
KEY_ACTIVE_STUDENTS = "socket:active:students"
KEY_ACTIVE_ADMINS = "socket:active:admins"


async def _get_redis():
    """Helper para obtener cliente Redis desde settings."""
    return aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)


async def _broadcast_active_users(sio_server):
    """Calcula totales y emite evento 'active_users'."""
    try:
        async with await _get_redis() as r:
            students_count = await r.scard(KEY_ACTIVE_STUDENTS)
            admins_count = await r.scard(KEY_ACTIVE_ADMINS)
            
        total = students_count + admins_count
        
        await sio_server.emit("active_users", {
            "total": total,
            "students": students_count,
            "admins": admins_count
        }, namespace=NAMESPACE)
        
    except Exception as e:
        logger.error(f"Error broadcasting active users: {e}")


def register_system_namespace(sio_server):
    """Registra los event handlers del namespace /system."""

    @sio_server.on("connect", namespace=NAMESPACE)
    async def on_connect(sid, environ):
        user = current_user_from_environ(environ)
        if not user:
            # Permitir conexión pero no contar si no es un usuario autenticado
            # O rechazar: return False
            # El dashboard index.html requiere usuario autenticado para ver,
            # asi que asumimos que si conecta es alguien valido.
            return True

        uid = user["sub"]
        role = user.get("role")
        
        # Guardar session info
        await sio_server.save_session(sid, {"user": user}, namespace=NAMESPACE)

        try:
            async with await _get_redis() as r:
                # Agregar SID al set de SIDs del usuario
                user_sids_key = KEY_USER_SIDS.format(uid=uid)
                await r.sadd(user_sids_key, sid)
                await r.expire(user_sids_key, 86400) # 24h safety expire

                # Agregar usuario a lista de activos segun rol
                # Asumimos que cualquier rol distinto de 'student' es 'admin' para efectos del dashboard
                # (staff, admin, etc.)
                if role == "student":
                    await r.sadd(KEY_ACTIVE_STUDENTS, uid)
                else:
                    await r.sadd(KEY_ACTIVE_ADMINS, uid)

            # Broadcast nuevos conteos
            await _broadcast_active_users(sio_server)
            
        except Exception as e:
            logger.error(f"Error en on_connect /system: {e}")

    @sio_server.on("disconnect", namespace=NAMESPACE)
    async def on_disconnect(sid):
        try:
            session = await sio_server.get_session(sid, namespace=NAMESPACE)
            user = session.get("user") if session else None
            
            if user:
                uid = user["sub"]
                role = user.get("role")
                
                async with await _get_redis() as r:
                    # Remover SID
                    user_sids_key = KEY_USER_SIDS.format(uid=uid)
                    await r.srem(user_sids_key, sid)
                    
                    # Verificar si quedan SIDs para este usuario
                    remaining_sids = await r.scard(user_sids_key)
                    
                    if remaining_sids == 0:
                        # Usuario ya no tiene conexiones activas
                        if role == "student":
                            await r.srem(KEY_ACTIVE_STUDENTS, uid)
                        else:
                            await r.srem(KEY_ACTIVE_ADMINS, uid)
                
                # Broadcast actualización
                await _broadcast_active_users(sio_server)
                
        except Exception as e:
            logger.error(f"Error en on_disconnect /system: {e}")
