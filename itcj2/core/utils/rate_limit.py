"""Rate limit backed por Redis.

Dos cosas viven aquí:

1. El limitador de LOGIN (`check_login_allowed` / `note_login_failure` /
   `reset_login_failures`). Cuenta FALLOS de autenticación por IP y por cuenta
   en una ventana móvil; si se excede el umbral, el login responde 429 hasta que
   la ventana expira. Falla ABIERTO a propósito: si Redis no está disponible NO
   bloquea (peor caso = sin rate limit, no caída). Claves: ``rl:login:ip:{ip}``
   y ``rl:login:acct:{account}``.

2. `check_and_count`, un contador por ventana REUSABLE para cualquier acción.
   Clave ``rl:{scope}:{key}``. Devuelve también los segundos que faltan para
   reintentar, que es lo que va en la cabecera `Retry-After`.

`fail_open` es parámetro y no constante porque el intercambio no es el mismo en
los dos casos: en el login, fallar abierto cambia seguridad por disponibilidad a
sabiendas; en una escritura ANÓNIMA que dispara correos, fallar abierto
significa que una caída de Redis elimina el único control que hay. Las rutas
públicas pasan `fail_open=False`.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _redis():
    try:
        from itcj2.core.utils.redis_conn import get_redis
        return get_redis()
    except Exception:  # pragma: no cover
        return None


def _cfg():
    from itcj2.config import get_settings
    s = get_settings()
    return (
        int(getattr(s, "LOGIN_FAIL_WINDOW", 300)),
        int(getattr(s, "LOGIN_FAIL_MAX_IP", 30)),
        int(getattr(s, "LOGIN_FAIL_MAX_ACCOUNT", 8)),
    )


def _ip_key(ip: str) -> str:
    return f"rl:login:ip:{ip}"


def _acct_key(account: str) -> str:
    return f"rl:login:acct:{account}"


def check_login_allowed(ip: str, account: str) -> bool:
    """True si el login puede intentarse; False si superó el umbral de fallos."""
    r = _redis()
    if r is None:
        return True  # fail-open
    _, max_ip, max_acct = _cfg()
    try:
        ip_fails = int(r.get(_ip_key(ip)) or 0)
        acct_fails = int(r.get(_acct_key(account)) or 0)
        return ip_fails < max_ip and acct_fails < max_acct
    except Exception as e:  # pragma: no cover
        logger.warning("rate_limit: check err (%s); fail-open", e)
        return True


def note_login_failure(ip: str, account: str) -> None:
    """Registra un fallo de login para IP y cuenta (con expiración de ventana)."""
    r = _redis()
    if r is None:
        return
    window, _, _ = _cfg()
    for key in (_ip_key(ip), _acct_key(account)):
        try:
            cnt = r.incr(key)
            if cnt == 1:
                r.expire(key, window)
        except Exception as e:  # pragma: no cover
            logger.warning("rate_limit: incr %s err (%s)", key, e)


def reset_login_failures(ip: str, account: str) -> None:
    """Limpia los contadores tras un login exitoso."""
    r = _redis()
    if r is None:
        return
    try:
        r.delete(_ip_key(ip), _acct_key(account))
    except Exception as e:  # pragma: no cover
        logger.warning("rate_limit: reset err (%s)", e)


def check_and_count(scope: str, key: str, *, limit: int, window: int,
                    fail_open: bool = True) -> tuple[bool, int]:
    """Cuenta un intento en ``rl:{scope}:{key}`` y dice si se permite.

    Devuelve ``(permitido, segundos_para_reintentar)``. Cuando permite, el
    segundo elemento es 0; cuando niega, es el TTL real de la clave (o la
    ventana completa si no hay TTL que consultar), listo para la cabecera
    ``Retry-After``.

    El intento se cuenta SIEMPRE, también el que rebasa el límite: el contador
    es un ``INCR`` a secas, y no contarlo obligaría a leer antes de escribir.
    A la ventana le da igual: su vencimiento se fija una sola vez, al crear la
    clave (``count == 1``), y ``INCR`` no toca el TTL de una clave que ya
    existe. Lo único que pasa es que el contador sigue subiendo por encima de
    ``limit``.

    ``fail_open=False`` NIEGA si Redis no responde (E2 del spec): tanto si no
    hay cliente como si la llamada revienta a mitad.
    """
    r = _redis()
    if r is None:
        return (True, 0) if fail_open else (False, window)

    redis_key = f"rl:{scope}:{key}"
    try:
        count = int(r.incr(redis_key))
        if count == 1:
            r.expire(redis_key, window)
        if count <= limit:
            return True, 0
        ttl = int(r.ttl(redis_key) or 0)
        return False, ttl if ttl > 0 else window
    except Exception as e:
        logger.warning("rate_limit: check_and_count %s err (%s); fail-%s",
                       redis_key, e, "open" if fail_open else "closed")
        return (True, 0) if fail_open else (False, window)
