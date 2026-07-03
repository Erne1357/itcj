"""Caché TTL de estilos de apps (color/icon_class) para serialización hot-path.

Patrón authz_cache (ver itcj2/core/services/authz_cache.py): Redis read-through,
fail-open a BD ante cualquier error, invalidación explícita en mutaciones de App
(create/update/delete en itcj2/core/api/authz.py). TTL corto (60s) como red de
seguridad si se omite una invalidación.

Consumidores: Notification.to_dict (app_icon/app_color_hex por notificación sin
query por fila) y, en fases posteriores, profile/users badges (F6/F7).
"""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Versionado: subir a v2 invalida de golpe si cambia el shape.
_KEY = "appstyle:v1:all"
_TTL = 60  # segundos (decisión spec §3.4)


def _redis():
    """Cliente Redis compartido. None si no disponible (fail-open)."""
    try:
        from itcj2.core.utils.redis_conn import get_redis
        return get_redis()
    except Exception as e:  # pragma: no cover - defensivo
        logger.warning("app_style_cache: sin Redis (%s)", e)
        return None


def _compute(db: Session) -> dict[str, dict]:
    from itcj2.core.models.app import App
    rows = db.query(App.key, App.color, App.icon_class).all()
    return {k: {"color": c, "icon_class": i} for k, c, i in rows}


def cached_app_styles(db: Session) -> dict[str, dict]:
    """{app_key: {"color": hex|None, "icon_class": str|None}} de TODAS las apps."""
    r = _redis()
    if r is not None:
        try:
            cached = r.get(_KEY)
            if cached is not None:
                return json.loads(cached)
        except Exception as e:
            logger.warning("app_style_cache: error leyendo (%s); fallback a BD", e)
            r = None  # no escribir si la lectura falló

    value = _compute(db)

    if r is not None:
        try:
            r.setex(_KEY, _TTL, json.dumps(value))
        except Exception as e:
            logger.warning("app_style_cache: error escribiendo (%s)", e)
    return value


def invalidate_app_styles() -> None:
    """Borra la entrada (create/update/delete de App)."""
    r = _redis()
    if r is None:
        return
    try:
        r.delete(_KEY)
    except Exception as e:
        logger.warning("app_style_cache: invalidate err (%s)", e)
