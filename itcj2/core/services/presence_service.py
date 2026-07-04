"""Presencia de usuarios derivada del namespace /notify (contrato C5).

Modelo: un sorted-set de Redis por bucket (presence:notify:students|staff|admins)
con member=str(uid) y score=unix-timestamp del último connect. La "verdad" es
aproximada por diseño (decisión D3 del spec): sin heartbeat, los miembros cuya
marca quedó fuera de la ventana PRESENCE_WINDOW_SECONDS se PODAN EN LECTURA
(restart-safe: un worker matado sin disparar disconnects no deja fantasmas
permanentes, expiran solos al leer).

Las funciones reciben el cliente Redis SÍNCRONO (redis_conn.get_redis(), que ya
es singleton por proceso => un solo cliente, no una conexión por evento). El
patrón "llamada sync corta dentro de handler async" es el establecido en
itcj2/sockets/slots.py.
"""
import time

from itcj2.config import get_settings

_KEY = "presence:notify:{bucket}"
BUCKETS = ("students", "staff", "admins")


def bucket_for(claims: dict) -> str:
    """Bucket de presencia según claims del JWT (C5).

    role=="admin" -> admins; role=="student" o `cn` presente -> students;
    resto -> staff. El orden importa: un admin con cn sigue siendo admin.
    """
    role = (claims.get("role") or "").lower()
    if role == "admin":
        return "admins"
    if role == "student" or claims.get("cn"):
        return "students"
    return "staff"


def mark_online(r, uid: int, bucket: str) -> None:
    """Registra/refresca la presencia del usuario en su bucket (ZADD upsert)."""
    r.zadd(_KEY.format(bucket=bucket), {str(int(uid)): time.time()})


def mark_offline(r, uid: int, bucket: str) -> None:
    """Remueve la presencia del usuario de su bucket."""
    r.zrem(_KEY.format(bucket=bucket), str(int(uid)))


def get_counts(r) -> dict:
    """Conteos vigentes {"total","students","staff","admins"} con poda en lectura."""
    cutoff = time.time() - get_settings().PRESENCE_WINDOW_SECONDS
    per_bucket = {}
    for bucket in BUCKETS:
        key = _KEY.format(bucket=bucket)
        r.zremrangebyscore(key, "-inf", cutoff)  # poda física en lectura
        per_bucket[bucket] = int(r.zcard(key))
    return {
        "total": per_bucket["students"] + per_bucket["staff"] + per_bucket["admins"],
        "students": per_bucket["students"],
        "staff": per_bucket["staff"],
        "admins": per_bucket["admins"],
    }
