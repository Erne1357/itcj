"""
Cache in-memory de catálogos de configuración con invalidación manual.

No usa TTL porque la invalidación se realiza explícitamente al modificar
un registro en la API. El cache es por proceso: en entornos con múltiples
workers (gunicorn, uvicorn multiprocess) cada worker mantiene su propio
cache. La invalidación es best-effort — si un worker actualiza el catálogo
sólo invalida su copia local. Bajo carga normal esto es aceptable dado que
las prioridades cambian raramente.
"""
import logging
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_PRIORITIES_BY_CODE: dict[str, dict] | None = None


def _ensure_loaded(db: Session) -> None:
    """Carga el cache de prioridades desde BD si aún no está poblado."""
    global _PRIORITIES_BY_CODE
    if _PRIORITIES_BY_CODE is None:
        from itcj2.apps.helpdesk.models.priority import Priority
        rows = db.query(Priority).order_by(Priority.display_order).all()
        _PRIORITIES_BY_CODE = {p.code: p.to_dict() for p in rows}
        logger.debug(f"catalog_cache: cargadas {len(_PRIORITIES_BY_CODE)} prioridades")


def get_priorities(db: Session, active_only: bool = True) -> list[dict]:
    """Devuelve lista de prioridades ordenada por display_order."""
    _ensure_loaded(db)
    items = list(_PRIORITIES_BY_CODE.values())
    if active_only:
        items = [p for p in items if p.get("is_active")]
    return items


def get_priority_by_code(db: Session, code: str) -> dict | None:
    """Lookup individual por code. Devuelve None si no existe."""
    _ensure_loaded(db)
    return _PRIORITIES_BY_CODE.get(code)


def get_priority_codes(db: Session, active_only: bool = True) -> set[str]:
    """Conjunto de codes válidos. Útil para validación rápida."""
    _ensure_loaded(db)
    if active_only:
        return {code for code, p in _PRIORITIES_BY_CODE.items() if p.get("is_active")}
    return set(_PRIORITIES_BY_CODE.keys())


def get_sla_hours(db: Session, code: str) -> int | None:
    """SLA en horas para la prioridad indicada por code. None si no existe."""
    _ensure_loaded(db)
    entry = _PRIORITIES_BY_CODE.get(code)
    if entry is None:
        return None
    return entry.get("sla_hours")


def invalidate_priorities() -> None:
    """Limpia el cache de prioridades. Debe llamarse tras cualquier operación write."""
    global _PRIORITIES_BY_CODE
    _PRIORITIES_BY_CODE = None
    logger.debug("catalog_cache: cache de prioridades invalidado")
