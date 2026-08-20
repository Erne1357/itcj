"""Revocación de sesión para JWTs stateless.

Cada usuario tiene una "versión de sesión" (entero en Redis). El JWT lleva el claim
``sv`` con la versión vigente al emitirse. El middleware compara: si ``sv`` del token
!= versión actual, el token queda revocado (se trata como no autenticado).

Bumpear la versión (logout / desactivación / cambio de rol) invalida al instante TODOS
los tokens del usuario, sin esperar a que expiren. Clave: ``session:v1:ver:{uid}``
(antes ``authz:v1:sessionver:{uid}``, que compartía prefijo con el caché de authz y
era borrada por su invalidación masiva).

Fail-open: si Redis no está disponible, ``current_version`` devuelve 0 y el middleware
sólo revoca ante un MISMATCH real; nunca bloquea por caída de Redis.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Namespace PROPIO. NO usar `authz:v1:` — es el prefijo del caché de authz, cuyo
# invalidate_all() lo barre entero (incidente del 2026-08-20: cambiar un permiso
# deslogueaba a toda la institución). Ver
# docs/superpowers/specs/2026-08-20-authz-cache-keyspace-collision.md
_KEY = "session:v1:ver:{uid}"

# Clave anterior, SOLO lectura. Ventana de transición: se migra en el sitio en el
# primer acceso para no poner en 0 la versión de nadie durante el despliegue.
# Retirable cuando `core migrate-session-keys` reporte 0 pendientes.
_LEGACY_KEY = "authz:v1:sessionver:{uid}"


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
        raw = r.get(_KEY.format(uid=user_id))
        if raw is not None:
            return int(raw)
        legacy = r.get(_LEGACY_KEY.format(uid=user_id))
        if legacy is None:
            return 0
        # RENAMENX: no pisa la clave nueva si otro worker ya migró en paralelo.
        try:
            r.renamenx(_LEGACY_KEY.format(uid=user_id), _KEY.format(uid=user_id))
        except Exception:
            pass
        return int(legacy)
    except Exception as e:
        logger.warning("session_service: current_version err (%s)", e)
        return 0


def bump_version(user_id: int) -> int:
    """Incrementa la versión → revoca todos los tokens actuales del usuario."""
    r = _redis()
    if r is None:
        return 0
    try:
        # Fuerza la migración de la clave legacy ANTES del INCR: si no, el INCR
        # crearía la clave nueva en 1 y bajaría la versión del usuario, revalidando
        # tokens viejos.
        current_version(user_id)
        return int(r.incr(_KEY.format(uid=user_id)))
    except Exception as e:
        logger.warning("session_service: bump err (%s)", e)
        return 0
