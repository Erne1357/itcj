"""Cliente `redis.asyncio` para el código que corre EN el event loop.

Espejo de `redis_conn.get_redis()`: misma URL/host/puerto/db, mismo
`decode_responses` y los mismos timeouts (1 s conectar / 2 s por operación; ver
el porqué en `redis_conn`). NO sirve para pub/sub `listen()` ni comandos con
bloqueo: el `socket_timeout` los cortaría. Existe porque el
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
# cliente y un singleton ingenuo rompería la suite. Las claves son débiles: aunque
# idealmente desaparecerían al morir un loop, la realidad es que el valor (client
# → pool → Connection → StreamWriter) mantiene una referencia fuerte al loop, así
# que la clave débil nunca muere. En producción no importa (un loop por proceso),
# pero en los tests cada TestClient/asyncio.run deja un cliente vivo hasta el exit.
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
            # BlockingConnectionPool y no el ConnectionPool por defecto: este
            # sostiene su `_lock` durante TODO `get_connection()` (connect +
            # handshake CLIENT SETINFO). Con Redis mudo cada conexión caducada
            # se descarta y las demás llamadas hacen cola: medido, 50
            # concurrentes = 100 s contra un agujero negro (2 s con este pool).
            # `max_connections` ~100 por proceso: holgura sobre la concurrencia
            # real del loop (threadpool anyio 40 + ráfagas de handshakes WS),
            # solo conexiones cliente baratas. `timeout` = el de operación: si
            # el pool se agota, lanza ConnectionError y entra en el fail-open
            # existente en vez de esperar sin fin.
            pool_kwargs = dict(
                max_connections=100,
                timeout=redis_conn.REDIS_SOCKET_TIMEOUT,
                socket_connect_timeout=redis_conn.REDIS_SOCKET_CONNECT_TIMEOUT,
                socket_timeout=redis_conn.REDIS_SOCKET_TIMEOUT,
                decode_responses=True,
            )
            if redis_conn.REDIS_URL:
                pool = aioredis.BlockingConnectionPool.from_url(
                    redis_conn.REDIS_URL, **pool_kwargs
                )
            else:
                pool = aioredis.BlockingConnectionPool(
                    host=redis_conn.REDIS_HOST,
                    port=redis_conn.REDIS_PORT,
                    db=redis_conn.REDIS_DB,
                    **pool_kwargs,
                )
            client = aioredis.Redis(connection_pool=pool)
            _clients[loop] = client
        return client
    except Exception as e:
        logger.warning("redis_conn_async: no se pudo crear el cliente (%s)", e)
        return None
