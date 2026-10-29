"""Presencia de revisión: «quién lo está revisando» (spec fase 3 §8.3).

Estado EFÍMERO y COSMÉTICO en Redis: nunca decide nada (la protección real
contra el doble dictamen es el bloqueo de proceso del service). Por eso todo
es fail-open: cualquier falla de Redis se loguea como warning y se comporta
como si nadie estuviera mirando.

Forma: un hash por (tipo, proceso), `titulatec:presence:{kind}:{process_id}`,
con un campo por usuario -> JSON `{"n": nombre, "t": epoch}`. La vigencia de
cada usuario (`FRESH_SECONDS`, 120 s) se mide con `t` al LEER; el hash entero
lleva `EXPIRE 300` para que lo abandonado se limpie solo. Nunca `KEYS`/`SCAN`
(el keyspace se comparte con la caché de authz): las lecturas son por clave
exacta y en UNA ida (pipeline) por página.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Iterable

logger = logging.getLogger(__name__)

FRESH_SECONDS = 120   # una marca más vieja ya no cuenta
HASH_TTL = 300        # EXPIRE del hash completo


def _now() -> float:
    """Epoch actual (función aparte para fijarla en pruebas)."""
    return time.time()


def _key(kind: str, process_id: int) -> str:
    return f"titulatec:presence:{kind}:{int(process_id)}"


class ReviewPresence:
    """Marcas de «lo tengo abierto» por tipo de revisión y proceso."""

    @staticmethod
    def touch(kind: str, process_id: int, user_id: int, name: str) -> None:
        """Registra (o renueva) que `user_id` tiene abierto el proceso."""
        try:
            from itcj2.core.utils.redis_conn import get_redis

            key = _key(kind, process_id)
            payload = json.dumps({"n": name, "t": _now()})
            pipe = get_redis().pipeline()
            pipe.hset(key, str(int(user_id)), payload)
            pipe.expire(key, HASH_TTL)
            pipe.execute()
        except Exception as exc:  # cosmético: nunca rompe la petición
            logger.warning("presencia touch falló: %s", exc)

    @staticmethod
    def clear(kind: str, process_id: int, user_id: int) -> None:
        """Borra la marca del usuario (al dictaminar o cerrar el detalle)."""
        try:
            from itcj2.core.utils.redis_conn import get_redis

            get_redis().hdel(_key(kind, process_id), str(int(user_id)))
        except Exception as exc:
            logger.warning("presencia clear falló: %s", exc)

    @staticmethod
    def viewers(kind: str, process_ids: Iterable[int],
                exclude_user_id: int) -> dict[int, list[str]]:
        """`{process_id: [nombres]}` de OTROS usuarios con marca vigente.

        Solo salen los procesos con al menos un visor. Una sola ida a Redis
        (pipeline) para toda la página; sin ids no hay ida.
        """
        ids = [int(p) for p in process_ids]
        if not ids:
            return {}
        try:
            from itcj2.core.utils.redis_conn import get_redis

            pipe = get_redis().pipeline()
            for pid in ids:
                pipe.hgetall(_key(kind, pid))
            hashes = pipe.execute()

            limite = _now() - FRESH_SECONDS
            propio = str(int(exclude_user_id))
            out: dict[int, list[str]] = {}
            for pid, h in zip(ids, hashes):
                vistos = []
                for uid, raw in (h or {}).items():
                    uid = uid.decode() if isinstance(uid, bytes) else uid
                    if uid == propio:
                        continue
                    try:
                        data = json.loads(raw)
                        if float(data["t"]) < limite:
                            continue
                        vistos.append((float(data["t"]), str(data["n"])))
                    except (ValueError, KeyError, TypeError):
                        continue
                if vistos:
                    out[pid] = [n for _, n in sorted(vistos)]
            return out
        except Exception as exc:
            logger.warning("presencia viewers falló: %s", exc)
            return {}
