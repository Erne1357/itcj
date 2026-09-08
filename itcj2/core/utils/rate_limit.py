"""Rate limit backed por Redis.

Dos cosas viven aqui:

1. El limitador de LOGIN (`check_login_allowed` / `note_login_failure` /
   `reset_login_failures`). Cuenta FALLOS de autenticacion por IP y por cuenta
   en una ventana movil; si se excede el umbral, el login responde 429 hasta que
   la ventana expira. Falla ABIERTO a proposito: si Redis no responde NO bloquea
   (peor caso = sin rate limit, no caida). Claves: ``rl:login:ip:{ip}`` y
   ``rl:login:acct:{account}``.

2. `check_and_count`, un contador por ventana REUSABLE para cualquier accion.
   Clave ``rl:{scope}:{key}``. Devuelve tambien los segundos que faltan para
   reintentar, que es lo que va en la cabecera `Retry-After`.

`fail_open` es parametro y no constante porque el intercambio no es el mismo en
los dos casos: en el login, fallar abierto cambia seguridad por disponibilidad a
sabiendas; en una escritura ANONIMA que dispara correos, fallar abierto
significa que una caida de Redis elimina el unico control que hay. Las rutas
publicas pasan `fail_open=False`.
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

    El intento se cuenta SIEMPRE, tambien el que rebasa el limite: si no, un
    atacante en bucle mantendria el contador clavado justo en el tope y la
    ventana nunca terminaria de correr.

    ``fail_open=False`` NIEGA si Redis no responde (E2 del spec).
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
    except Exception as e:  # pragma: no cover
        logger.warning("rate_limit: check_and_count %s err (%s); fail-%s",
                       redis_key, e, "open" if fail_open else "closed")
        return (True, 0) if fail_open else (False, window)
