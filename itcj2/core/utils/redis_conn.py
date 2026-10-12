import os

import redis

REDIS_URL = os.getenv("REDIS_URL")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

# Default 45s (alineado con los docs de AgendaTec). Durante el thundering herd,
# un hold abandonado bloquea un slot escaso solo ~45s en vez de 120s.
# Override por entorno con SLOT_HOLD_SECONDS en .env.prod si se requiere otro valor.
SLOT_HOLD_SECONDS = int(os.getenv("SLOT_HOLD_SECONDS", "45"))

# Timeouts de los clientes de la app (decisión del dueño: 1 s conectar, 2 s por
# operación). Sin ellos, un Redis «agujero negro» (acepta TCP y no responde)
# cuelga cada operación para siempre: autenticación en cada petición con `sv`,
# holds de AgendaTec. Con ellos la operación lanza y los caminos fail-open
# (p. ej. `current_version` -> None) toman el relevo.
# TRAMPA: `socket_timeout` también corta las operaciones bloqueantes legítimas
# (pub/sub `listen()`, BLPOP, XREAD BLOCK). Este cliente NO debe usarse para
# ellas: el suscriptor de `task_events` (main.py) crea su propio cliente sin
# timeout a propósito. Override por entorno si hiciera falta.
REDIS_SOCKET_CONNECT_TIMEOUT = float(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT", "1"))
REDIS_SOCKET_TIMEOUT = float(os.getenv("REDIS_SOCKET_TIMEOUT", "2"))

_redis = None


def get_redis():
    global _redis
    if _redis is None:
        timeouts = dict(
            socket_connect_timeout=REDIS_SOCKET_CONNECT_TIMEOUT,
            socket_timeout=REDIS_SOCKET_TIMEOUT,
        )
        if REDIS_URL:
            _redis = redis.Redis.from_url(REDIS_URL, decode_responses=True, **timeouts)
        else:
            _redis = redis.Redis(
                host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True, **timeouts
            )
    return _redis


def get_hold_ttl():
    return SLOT_HOLD_SECONDS
