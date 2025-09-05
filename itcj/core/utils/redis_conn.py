# utils/redis_conn.py
import os
import redis

# Prioriza REDIS_URL si la tienes (formato: redis://host:port/0)
REDIS_URL = os.getenv("REDIS_URL")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB   = int(os.getenv("REDIS_DB", "0"))

# TTL del hold (segundos)
SLOT_HOLD_SECONDS = int(os.getenv("SLOT_HOLD_SECONDS", "120"))

_redis = None

def get_redis():
    global _redis
    if _redis is None:
        if REDIS_URL:
            _redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        else:
            _redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    return _redis

def get_hold_ttl():
    return SLOT_HOLD_SECONDS
