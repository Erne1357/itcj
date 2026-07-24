"""Rate limit de login backed por Redis.

Cuenta FALLOS de autenticación por IP y por cuenta en una ventana móvil. Si se
excede el umbral, el login responde 429 hasta que la ventana expira. Fail-open:
si Redis no está disponible NO bloquea (peor caso = sin rate limit, no caída).

Claves: ``rl:login:ip:{ip}`` y ``rl:login:acct:{account}``.
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
