"""
Cache invalidable de prioridades para maint.

Proporciona acceso rápido al catálogo de prioridades (MaintPriority) con
degradación defensiva al dict SLA_HOURS hardcoded cuando la tabla no existe
o la BD no está disponible.

El cache es de módulo (no lru_cache) para permitir invalidación explícita.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ==================== CACHE DE MÓDULO ====================

_priorities_cache: Optional[list] = None   # lista de dicts raw
_priority_codes_cache: Optional[set] = None
_sla_hours_cache: Optional[dict] = None    # code -> sla_hours


def _fallback_sla_hours() -> dict:
    """Retorna el dict hardcoded como último recurso."""
    try:
        from itcj2.apps.maint.models.ticket import SLA_HOURS
        return dict(SLA_HOURS)
    except Exception:
        return {'URGENTE': 2, 'ALTA': 24, 'MEDIA': 72, 'BAJA': 168}


def _load_from_db() -> list:
    """
    Abre una sesión efímera, consulta maint_priority, cierra la sesión.
    Retorna lista de dicts ordenada por display_order.
    Lanza excepción si falla (el caller hace el try/except).
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.maint.models.priority import MaintPriority

    db = SessionLocal()
    try:
        rows = (
            db.query(MaintPriority)
            .order_by(MaintPriority.display_order)
            .all()
        )
        return [_row_to_dict(r) for r in rows]
    finally:
        db.close()


def _row_to_dict(p) -> dict:
    return {
        "id": p.id,
        "code": p.code,
        "label": p.label,
        "color": p.color,
        "badge_class": p.badge_class,
        "sla_hours": p.sla_hours,
        "is_default": p.is_default,
        "display_order": p.display_order,
        "is_active": p.is_active,
    }


def _ensure_cache() -> list:
    """
    Rellena el cache si está vacío.  Degrada silenciosamente si la BD falla.
    Retorna la lista (puede estar vacía si la BD falla).
    """
    global _priorities_cache, _priority_codes_cache, _sla_hours_cache

    if _priorities_cache is not None:
        return _priorities_cache

    try:
        rows = _load_from_db()
        _priorities_cache = rows
        _priority_codes_cache = {r["code"] for r in rows if r["is_active"]}
        _sla_hours_cache = {r["code"]: r["sla_hours"] for r in rows}
        return _priorities_cache
    except Exception as exc:
        logger.warning(f"catalog_cache: no se pudo cargar prioridades desde BD ({exc!r}); usando fallback")
        # Dejar cache en None para que se reintente en el siguiente request
        return []


# ==================== API PÚBLICA ====================

def get_priorities(db=None) -> list:
    """
    Retorna todas las prioridades ordenadas por display_order como lista de dicts.
    `db` se acepta por compatibilidad pero no se usa (el cache usa sesión efímera propia).
    """
    rows = _ensure_cache()
    if rows:
        return rows
    # Fallback: convertir SLA_HOURS a formato dict mínimo
    fallback = _fallback_sla_hours()
    return [
        {"id": None, "code": k, "label": k.capitalize(), "color": None,
         "badge_class": None, "sla_hours": v, "is_default": False,
         "display_order": i, "is_active": True}
        for i, (k, v) in enumerate(fallback.items())
    ]


def get_priority_codes(db=None) -> set:
    """
    Retorna el set de codes ACTIVOS.
    Fallback: keys del dict hardcoded.
    """
    _ensure_cache()
    if _priority_codes_cache is not None:
        return _priority_codes_cache
    return set(_fallback_sla_hours().keys())


def get_sla_hours(code: str, db=None) -> int:
    """
    Retorna las horas SLA para el code dado.
    Si no existe en cache ni en fallback retorna 72 (MEDIA por defecto).
    """
    _ensure_cache()
    if _sla_hours_cache:
        if code in _sla_hours_cache:
            return _sla_hours_cache[code]
    # Fallback al hardcoded
    fallback = _fallback_sla_hours()
    return fallback.get(code, 72)


def invalidate_priorities() -> None:
    """Limpia el cache para que se recargue en el siguiente acceso."""
    global _priorities_cache, _priority_codes_cache, _sla_hours_cache
    _priorities_cache = None
    _priority_codes_cache = None
    _sla_hours_cache = None
    logger.debug("catalog_cache: cache de prioridades invalidado")
