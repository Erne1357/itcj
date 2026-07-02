"""Revocación de sesión para JWTs stateless.

Cada usuario tiene una "versión de sesión" (entero en Redis). El JWT lleva el claim
``sv`` con la versión vigente al emitirse. El middleware compara: si ``sv`` del token
!= versión actual, el token queda revocado (se trata como no autenticado).

Bumpear la versión (logout / desactivación / cambio de rol) invalida al instante TODOS
los tokens del usuario, sin esperar a que expiren. Clave: ``authz:v1:sessionver:{uid}``.

Fail-open: si Redis no está disponible, ``current_version`` devuelve 0 y el middleware
sólo revoca ante un MISMATCH real; nunca bloquea por caída de Redis.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_KEY = "authz:v1:sessionver:{uid}"


def _redis():
    try:
        from itcj2.core.utils.redis_conn import get_redis
        return get_redis()
    except Exception:  # pragma: no cover
        return None


def current_version(user_id: int) -> int:
    """Versión de sesión vigente del usuario (0 si nunca se bumpeó / Redis caído)."""
    r = _redis()
    if r is None:
        return 0
    try:
        return int(r.get(_KEY.format(uid=user_id)) or 0)
    except Exception as e:  # pragma: no cover
        logger.warning("session_service: current_version err (%s)", e)
        return 0


def bump_version(user_id: int) -> int:
    """Incrementa la versión → revoca todos los tokens actuales del usuario."""
    r = _redis()
    if r is None:
        return 0
    try:
        return int(r.incr(_KEY.format(uid=user_id)))
    except Exception as e:  # pragma: no cover
        logger.warning("session_service: bump err (%s)", e)
        return 0
