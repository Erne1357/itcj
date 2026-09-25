"""Presencia de usuarios derivada del namespace /notify (contrato C5).

Modelo: un sorted-set de Redis por bucket (presence:notify:students|staff|admins)
con member=str(uid) y score=unix-timestamp del último connect. La "verdad" es
aproximada por diseño (decisión D3 del spec): los miembros cuya marca quedó
fuera de la ventana PRESENCE_WINDOW_SECONDS se PODAN EN LECTURA (restart-safe:
un worker matado sin disparar disconnects no deja fantasmas permanentes,
expiran solos al leer).

RONDA 3 — POR QUÉ EXISTE EL LATIDO (`touch`): la poda en lectura SIN nada que
refresque la marca no medía "quién está dentro", medía "quién se conectó en los
últimos 5 minutos". Medido en producción (38 h de datos): el 93,7 % del tiempo
había sockets abiertos en /notify con presencia 0, porque solo el `connect`
escribía y una sesión de trabajo normal dura mucho más que la ventana. Ahora el
shell late por el socket que YA está abierto (evento `presence_heartbeat`) cada
~60 s y `touch` vuelve a meter la marca: con la ventana intacta en 300 s eso da
5 latidos de tolerancia antes de que a alguien se le considere fuera (una red
intermitente no lo saca del panel).

El latido trae además la app que el usuario tiene abierta en el iframe del
shell, que se acumula en un zset por app (presence:app:{app_key}) con la MISMA
poda en lectura. Normalizada contra el vocabulario cerrado de app_keys
(`observability.route`): cualquier cosa fuera de él cuenta como `otro`, para que
una app nueva sin registrar se note en el tablero en vez de inventar una serie.

Las funciones reciben el cliente Redis SÍNCRONO (redis_conn.get_redis(), que ya
es singleton por proceso => un solo cliente, no una conexión por evento). El
patrón "llamada sync corta dentro de handler async" es el establecido en
itcj2/sockets/slots.py. Cada escritura/lectura que toca más de una clave va en
UN pipeline: el latido es por usuario y por minuto, no se paga una ida-vuelta
por zset.
"""
import time

from itcj2.config import get_settings
from itcj2.observability.route import APP_KEYS, OTHER_KEY, normalize_app_key

_KEY = "presence:notify:{bucket}"
_APP_KEY = "presence:app:{app}"
BUCKETS = ("students", "staff", "admins")

# Orden determinista (el conjunto de `route` no lo tiene) para que la familia
# de métricas salga siempre con las mismas series en el mismo orden.
APPS = tuple(sorted(APP_KEYS)) + (OTHER_KEY,)


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


def touch(r, uid: int, bucket: str, app, previous_app=None) -> str:
    """Latido: refresca la marca del usuario en su bucket Y en la app reportada.

    `app` llega de un cliente, así que se normaliza aquí (ver docstring del
    módulo); devuelve la app_key normalizada para que el handler la guarde en
    la sesión del socket y sepa de dónde retirarlo la próxima vez.

    `previous_app` es la app que ESTE socket reportó en su latido anterior: si
    cambió, se retira la marca vieja en el mismo pipeline. Sin eso, navegar de
    helpdesk a maint dejaría al usuario contado en las dos hasta que la ventana
    lo podara (hasta 5 minutos de fantasma en una app que ya cerró).
    """
    app_key = normalize_app_key(app)
    previous_key = normalize_app_key(previous_app) if previous_app else None
    member = str(int(uid))
    now = time.time()
    pipe = r.pipeline()
    pipe.zadd(_KEY.format(bucket=bucket), {member: now})
    pipe.zadd(_APP_KEY.format(app=app_key), {member: now})
    if previous_key is not None and previous_key != app_key:
        pipe.zrem(_APP_KEY.format(app=previous_key), member)
    pipe.execute()
    return app_key


def mark_offline(r, uid: int, bucket: str, app=None) -> None:
    """Remueve la presencia del usuario de su bucket y, si se sabe cuál, del
    zset de la app que reportaba su último latido (UNA ida a Redis)."""
    member = str(int(uid))
    pipe = r.pipeline()
    pipe.zrem(_KEY.format(bucket=bucket), member)
    if app:
        pipe.zrem(_APP_KEY.format(app=normalize_app_key(app)), member)
    pipe.execute()


def mark_app_offline(r, uid: int, app) -> None:
    """Retira al usuario SOLO del zset de una app, dejando su bucket intacto.

    Es el caso multi-pestaña: se cierra la pestaña que tenía abierta esta app
    pero el usuario sigue dentro por otra. Si la que queda tiene la misma app,
    su propio latido la re-afirma en <=60 s — un subconteo acotado a un latido
    es preferible a un fantasma de hasta 300 s en una app que nadie abrió.
    """
    if not app:
        return
    r.zrem(_APP_KEY.format(app=normalize_app_key(app)), str(int(uid)))


def get_counts(r) -> dict:
    """Conteos vigentes {"total","students","staff","admins"} con poda en lectura.

    `total` es el tamaño de la UNIÓN de uids vigentes entre los 3 buckets, no la
    suma de los conteos por bucket: un mismo uid puede aparecer transitoriamente
    en 2 buckets a la vez (claims cambiaron —p.ej. cambio de rol— mientras la
    entrada vieja seguía dentro de PRESENCE_WINDOW_SECONDS, o entrada "fantasma"
    de un worker matado). En ese caso cada bucket lo sigue contando (semántica
    documentada, no un bug), pero `total` lo cuenta UNA sola vez.

    Una sola ida-vuelta a Redis vía pipeline: 3 podas (zremrangebyscore) + 3
    lecturas de miembros vigentes (zrangebyscore), en ese orden.
    """
    cutoff = time.time() - get_settings().PRESENCE_WINDOW_SECONDS
    pipe = r.pipeline()
    for bucket in BUCKETS:
        pipe.zremrangebyscore(_KEY.format(bucket=bucket), "-inf", cutoff)  # poda física en lectura
    for bucket in BUCKETS:
        pipe.zrangebyscore(_KEY.format(bucket=bucket), cutoff, "+inf")
    results = pipe.execute()
    members = dict(zip(BUCKETS, results[len(BUCKETS):]))
    per_bucket = {bucket: len(members[bucket]) for bucket in BUCKETS}
    uid_union = set().union(*members.values())
    return {
        "total": len(uid_union),
        "students": per_bucket["students"],
        "staff": per_bucket["staff"],
        "admins": per_bucket["admins"],
    }


def get_app_counts(r) -> dict:
    """{app_key: usuarios DISTINTOS vigentes} para TODO `APPS`, con poda en lectura.

    Distintos sale gratis: el member del zset es el uid, así que dos latidos del
    mismo usuario (o dos pestañas suyas en la misma app) son un solo member.

    Se devuelven las 10 claves siempre, incluidas las que valen 0: en el panel
    una serie ausente no se distingue de una que vale 0, y la app "vacía" es
    justo el dato que interesa mirar.

    Una sola ida-vuelta a Redis vía pipeline: una poda + un `zcard` por app, en
    ese orden. `zcard` en vez de `zrangebyscore` porque aquí no hace falta la
    unión de uids (cada app se cuenta sola) y así los uids ni salen de Redis.
    """
    cutoff = time.time() - get_settings().PRESENCE_WINDOW_SECONDS
    pipe = r.pipeline()
    for app in APPS:
        pipe.zremrangebyscore(_APP_KEY.format(app=app), "-inf", cutoff)  # poda física
    for app in APPS:
        pipe.zcard(_APP_KEY.format(app=app))
    results = pipe.execute()
    return dict(zip(APPS, (int(n) for n in results[len(APPS):])))
