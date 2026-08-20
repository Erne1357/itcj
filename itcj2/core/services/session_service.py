"""Revocación de sesión para JWTs stateless.

Cada usuario tiene una "época de sesión" (``core_users.session_epoch``). El JWT
lleva el claim ``sv`` con la época vigente al emitirse. El middleware compara: si
``sv`` del token != época actual, el token queda revocado (se trata como no
autenticado).

Bumpear la época (logout / desactivación / cambio de rol) invalida al instante
TODOS los tokens del usuario, sin esperar a que expiren.

**Postgres es la fuente de verdad.** Redis solo cachea la época bajo
``session:v1:ver:{uid}`` con TTL (``_TTL``): perder la clave (restart, eviction,
un barrido accidental) no resucita sesiones cerradas ni desloguea a nadie — el
valor se repuebla desde la BD. Antes el entero vivía SOLO en Redis (sin AOF,
compartido con Celery/Socket.IO/holds de AgendaTec).

Modo de fallo: ``current_version`` devuelve ``None`` SOLO cuando no puede
consultar ningún almacén (Redis y Postgres caídos). Los consumidores (middleware,
socket_auth) tratan ``None`` como "sin información" y NO revocan — fail-open real.
Solo un MISMATCH numérico revoca. Que el usuario no exista NO es ``None`` sino
``0``: su token con ``sv >= 1`` debe seguir quedando revocado.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Namespace PROPIO. NO usar `authz:v1:` — es el prefijo del caché de authz, cuyo
# invalidate_all() lo barre entero (incidente del 2026-08-20: cambiar un permiso
# deslogueaba a toda la institución). Ver
# docs/superpowers/specs/2026-08-20-authz-cache-keyspace-collision.md
_KEY = "session:v1:ver:{uid}"

_TTL = 3600  # segundos que vive la copia en Redis (Postgres es la verdad)

# Escritura monótona del caché: puede SUBIR el valor, nunca bajarlo.
# Postgres es la verdad y su epoch sólo crece; sin esta guarda, dos bumps
# concurrentes —o el SET tardío de un lector que leyó Postgres ANTES de un
# bump— podrían dejar en Redis un valor MENOR que el real, y una sesión ya
# revocada seguiría autenticando hasta que expirara el TTL.
_SET_IF_GREATER = """
local cur = redis.call('GET', KEYS[1])
if (not cur) or (tonumber(cur) < tonumber(ARGV[1])) then
  redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
end
return 1
"""


def _cache_epoch(r, user_id: int, value: int) -> None:
    """Publica la época en Redis sin poder bajarla nunca (best-effort).

    Antes de esta tarea el contador era un ``INCR`` sobre la ÚNICA fuente de
    verdad, así que el valor cacheado no podía quedar por debajo del real.
    Separar verdad (Postgres) de caché (Redis) introdujo un read-modify-write
    entre procesos; la guarda lo cierra. Un fallo de escritura del caché NO es
    fatal: el próximo lector repuebla desde Postgres.
    """
    try:
        r.eval(_SET_IF_GREATER, 1, _KEY.format(uid=user_id), value, _TTL)
    except Exception as e:
        logger.warning("session_service: no se pudo cachear la época (%s)", e)


def _redis():
    try:
        from itcj2.core.utils.redis_conn import get_redis
        return get_redis()
    except Exception:  # pragma: no cover
        return None


def _read_epoch_from_db(user_id: int) -> int | None:
    """Lee `core_users.session_epoch`.

    - ``N``    → época del usuario.
    - ``0``    → la consulta FUNCIONÓ y el usuario no existe. Es 0 y no ``None``
      a propósito: restaura la semántica previa a esta tarea, donde la ausencia
      de clave valía 0 y por tanto un token con ``sv >= 1`` de un usuario
      borrado quedaba revocado. Devolver ``None`` significaría "no se pudo
      determinar" y lo dejaría autenticando hasta que expirara. NO simplificar
      ambos casos al mismo valor: distinguirlos es justo el punto.
    - ``None`` → la consulta FALLÓ (BD inalcanzable). El llamador no debe revocar.
    """
    from sqlalchemy import select

    from itcj2.core.models.user import User
    from itcj2.database import SessionLocal

    db = SessionLocal()
    try:
        val = db.execute(select(User.session_epoch).where(User.id == user_id)).scalar_one_or_none()
        db.rollback()
        return int(val) if val is not None else 0
    except Exception as e:
        logger.warning("session_service: lectura de session_epoch falló (%s)", e)
        try:
            db.rollback()
        except Exception:
            pass
        return None
    finally:
        try:
            db.close()
        except Exception:
            pass


def current_version(user_id: int) -> int | None:
    """Época de sesión vigente. Read-through: Redis primero, Postgres si hay MISS.

    - ``0``    → el usuario nunca fue bumpeado, O no existe (fila ausente). En
      ambos casos un token con ``sv >= 1`` queda revocado, como antes de esta tarea.
    - ``N>0``  → época vigente.
    - ``None`` → no se pudo determinar: ni Redis ni Postgres pudieron responder.
      El llamador NO debe revocar. "El usuario no existe" NO es este caso.
    """
    r = _redis()
    if r is not None:
        try:
            raw = r.get(_KEY.format(uid=user_id))
            if raw is not None:
                return int(raw)
        except Exception as e:
            logger.warning("session_service: current_version redis err (%s)", e)
            r = None

    epoch = _read_epoch_from_db(user_id)
    if epoch is None:
        return None

    if r is not None:
        _cache_epoch(r, user_id, epoch)
    return epoch


def bump_version(user_id: int, db=None) -> int | None:
    """Incrementa la época → revoca todos los tokens actuales del usuario.

    Postgres es la fuente de verdad. Si se pasa ``db``, el UPDATE va en ESA
    transacción: permite que el bump sea atómico con el cambio que lo motiva
    (p.ej. ``is_active = False``), cerrando la carrera de users_admin.
    """
    from sqlalchemy import text

    owns = db is None
    if owns:
        from itcj2.database import SessionLocal
        db = SessionLocal()
    try:
        val = db.execute(
            text("UPDATE core_users SET session_epoch = session_epoch + 1 "
                 "WHERE id = :uid RETURNING session_epoch"),
            {"uid": user_id},
        ).scalar_one_or_none()
        if owns:
            db.commit()
    except Exception as e:
        logger.warning("session_service: bump err (%s)", e)
        if owns:
            try:
                db.rollback()
            except Exception:
                pass
        return None
    finally:
        if owns:
            try:
                db.close()
            except Exception:
                pass

    if val is None:
        return None
    val = int(val)

    r = _redis()
    if r is not None:
        if owns:
            _cache_epoch(r, user_id, val)
        else:
            # El caller aún no commiteó: publicar el valor nuevo podría revertirse.
            # Se invalida y el próximo lector lo relee de Postgres ya commiteado.
            try:
                r.delete(_KEY.format(uid=user_id))
            except Exception:
                pass
    return val
