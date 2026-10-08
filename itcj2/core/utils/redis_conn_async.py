"""Cliente `redis.asyncio` para el código que corre EN el event loop.

Espejo de `redis_conn.get_redis()`: misma URL/host/puerto/db, mismo
`decode_responses`, y —como allí— sin timeouts propios. Existe porque el
cliente síncrono, llamado desde una corrutina, bloquea el loop entero del
worker mientras espera a Redis (alerta `ItcjEventLoopBloqueosLargos`).
"""
import asyncio
import logging
import weakref

import redis.asyncio as aioredis

from itcj2.core.utils import redis_conn

logger = logging.getLogger(__name__)

# Un cliente POR event loop, no un singleton. El pool de `redis.asyncio` queda
# atado al loop donde abrió sus conexiones; reutilizarlo desde otro loop da
# «attached to a different loop». En producción hay un loop por proceso
# uvicorn (4 clientes con --workers 4), pero `TestClient` crea un loop nuevo por
# cliente y un singleton ingenuo rompería la suite. Las claves son débiles: al
# morir un loop su entrada desaparece y un `id()` reciclado no puede devolver un
# cliente de un loop muerto.
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, aioredis.Redis]" = (
    weakref.WeakKeyDictionary()
)


def get_redis_async() -> aioredis.Redis | None:
    """Cliente del loop en curso, o `None` si no hay loop o no se pudo crear.

    Las constantes se leen de `redis_conn` en el momento de crear el cliente, no
    al importar: así hereda cualquier ajuste hecho allí (la suite redirige a la
    db 15 reescribiéndolas)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    try:
        client = _clients.get(loop)
        if client is None:
            if redis_conn.REDIS_URL:
                client = aioredis.Redis.from_url(redis_conn.REDIS_URL, decode_responses=True)
            else:
                client = aioredis.Redis(
                    host=redis_conn.REDIS_HOST,
                    port=redis_conn.REDIS_PORT,
                    db=redis_conn.REDIS_DB,
                    decode_responses=True,
                )
            _clients[loop] = client
        return client
    except Exception as e:
        logger.warning("redis_conn_async: no se pudo crear el cliente (%s)", e)
        return None
