"""Caché read-through de autorización por (usuario, app) en Redis.

Colapsa las ~18-20 queries por request protegido (effective_perms +
has_any_assignment, sin caché) a 1-2 GET de Redis en el hot path.
Es la tarea 1.1 del PLAN_INFRA_ROADMAP.md (el mayor win de la auditoría).

Diseño — un wrapper cacheado POR FUNCIÓN (no un bundle unificado):

    cached_roles(...)          -> envuelve authz_service.user_roles_in_app
    cached_perms(...)          -> envuelve authz_service.get_user_permissions_for_app
    cached_has_assignment(...) -> envuelve authz_service.has_any_assignment

Cada wrapper, en MISS, llama exactamente a la misma función de authz_service
que la dependencia usaba antes. Esto preserva el comportamiento (y los mocks de
los tests, que parchean esas funciones): si Redis no está disponible, el wrapper
cae a la función original — fail-open.

Propiedades:
- **Read-through y lazy:** la entrada se llena en el PRIMER request que la
  necesita (no al login). NO está atada a la sesión: si el usuario hace logout,
  su JWT expira o cierra el navegador, deja de pedir y la entrada expira por TTL.
- **TTL corto** (``AUTHZ_CACHE_TTL``, default 300s): red de seguridad si se
  omite alguna invalidación.
- **Fail-open:** ante cualquier error de Redis se computa contra la BD; el caché
  NUNCA bloquea ni rompe la autorización (peor caso = lento, no inseguro).
- **Invalidación explícita** en cada mutación de roles/permisos/puestos.

Claves: ``authz:v1:{kind}:{app_key}:{user_id}`` con kind ∈ {roles, perms, has}.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Prefijo versionado: subir a v2 invalida TODO de golpe si cambia el formato.
_PREFIX = "authz:v1"
_KINDS = ("roles", "perms", "has")


def _ttl() -> int:
    from itcj2.config import get_settings
    return int(getattr(get_settings(), "AUTHZ_CACHE_TTL", 300))


def _key(kind: str, app_key: str, user_id: int) -> str:
    return f"{_PREFIX}:{kind}:{app_key}:{user_id}"


def _redis():
    """Cliente Redis síncrono compartido. None si no se puede obtener."""
    try:
        from itcj2.core.utils.redis_conn import get_redis
        return get_redis()
    except Exception as e:  # pragma: no cover - defensivo
        logger.warning("authz_cache: no se pudo obtener Redis (%s)", e)
        return None


def _get_or_set(kind: str, app_key: str, user_id: int, compute: Callable[[], object]):
    """Read-through genérico. ``compute`` produce un valor JSON-serializable."""
    key = _key(kind, app_key, user_id)
    r = _redis()

    if r is not None:
        try:
            cached = r.get(key)
            if cached is not None:
                return json.loads(cached)
        except Exception as e:
            logger.warning("authz_cache: error leyendo %s (%s); fallback a BD", key, e)
            r = None  # no escribir si la lectura falló

    value = compute()

    if r is not None:
        try:
            r.setex(key, _ttl(), json.dumps(value))
        except Exception as e:
            logger.warning("authz_cache: error escribiendo %s (%s)", key, e)

    return value


# ---------------------------------------------------------------------------
# Wrappers cacheados (lo que consumen las dependencias de FastAPI)
# ---------------------------------------------------------------------------
def cached_roles(db: Session, user_id: int, app_key: str) -> set:
    """Roles efectivos (directos + puestos). Envuelve user_roles_in_app."""
    from itcj2.core.services.authz_service import user_roles_in_app
    data = _get_or_set(
        "roles", app_key, user_id,
        lambda: sorted(user_roles_in_app(db, user_id, app_key, include_positions=True)),
    )
    return set(data)


def cached_perms(db: Session, user_id: int, app_key: str) -> set:
    """Permisos efectivos. Envuelve get_user_permissions_for_app."""
    from itcj2.core.services.authz_service import get_user_permissions_for_app
    data = _get_or_set(
        "perms", app_key, user_id,
        lambda: sorted(get_user_permissions_for_app(db, user_id, app_key, include_positions=True)),
    )
    return set(data)


def cached_has_assignment(db: Session, user_id: int, app_key: str) -> bool:
    """¿Tiene alguna asignación en la app? Envuelve has_any_assignment."""
    from itcj2.core.services.authz_service import has_any_assignment
    return bool(_get_or_set(
        "has", app_key, user_id,
        lambda: bool(has_any_assignment(db, user_id, app_key, include_positions=True)),
    ))


# ---------------------------------------------------------------------------
# Invalidación
# ---------------------------------------------------------------------------
def invalidate_user_app(user_id: int, app_key: str) -> None:
    """Borra el caché de un usuario en UNA app (grant/revoke role/perm directo)."""
    r = _redis()
    if r is None:
        return
    try:
        r.delete(*[_key(k, app_key, user_id) for k in _KINDS])
    except Exception as e:
        logger.warning("authz_cache: invalidate_user_app(%s,%s) err (%s)", user_id, app_key, e)


def invalidate_user(user_id: int) -> None:
    """Borra el caché de un usuario en TODAS las apps.

    Para cambios que afectan varias apps del mismo usuario: asignar/quitar un
    puesto (UserPosition), que puede otorgar roles/perms en múltiples apps.
    """
    r = _redis()
    if r is None:
        return
    try:
        keys = list(r.scan_iter(match=f"{_PREFIX}:*:*:{user_id}", count=500))
        if keys:
            r.delete(*keys)
    except Exception as e:
        logger.warning("authz_cache: invalidate_user(%s) err (%s)", user_id, e)


def invalidate_all() -> None:
    """Borra TODO el caché de authz.

    Para cambios role/position-wide que afectan a muchos usuarios:
    RolePermission (perms de un rol), PositionAppRole / PositionAppPerm
    (config de un puesto), activar/desactivar un puesto. Son operaciones de
    admin poco frecuentes; el SCAN sobre un keyspace pequeño es aceptable.
    """
    r = _redis()
    if r is None:
        return
    try:
        keys = list(r.scan_iter(match=f"{_PREFIX}:*", count=1000))
        if keys:
            r.delete(*keys)
    except Exception as e:
        logger.warning("authz_cache: invalidate_all err (%s)", e)
