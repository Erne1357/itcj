"""
Cache invalidable de catálogos para maint.

Proporciona acceso rápido a:
- MaintPriority          → get_priorities / get_priority_codes / get_sla_hours
- MaintMaintenanceType   → get_maint_types / get_maint_type_codes
- MaintServiceOrigin     → get_service_origins / get_service_origin_codes
- MaintArea              → get_areas / get_area_codes / get_area_by_code / invalidate_areas

Cada catálogo tiene degradación defensiva a valores hardcoded cuando la
tabla no existe o la BD no está disponible. El cache es de módulo (no
lru_cache) para permitir invalidación explícita tras cada escritura.
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


# ==================== MAINT TYPES ====================

_maint_types_cache: Optional[list] = None
_maint_type_codes_cache: Optional[set] = None

_FALLBACK_MAINT_TYPE_CODES = {'PREVENTIVO', 'CORRECTIVO'}


def _load_maint_types_from_db() -> list:
    """
    Abre una sesión efímera, consulta maint_maintenance_type, cierra la sesión.
    Retorna lista de dicts ordenada por display_order.
    Lanza excepción si falla (el caller hace el try/except).
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.maint.models.simple_catalog import MaintMaintenanceType

    db = SessionLocal()
    try:
        rows = (
            db.query(MaintMaintenanceType)
            .order_by(MaintMaintenanceType.display_order)
            .all()
        )
        return [_maint_type_to_dict(r) for r in rows]
    finally:
        db.close()


def _maint_type_to_dict(m) -> dict:
    return {
        "id": m.id,
        "code": m.code,
        "label": m.label,
        "display_order": m.display_order,
        "is_active": m.is_active,
    }


def _ensure_maint_types_cache() -> list:
    """Rellena el cache si está vacío. Degrada silenciosamente si la BD falla."""
    global _maint_types_cache, _maint_type_codes_cache

    if _maint_types_cache is not None:
        return _maint_types_cache

    try:
        rows = _load_maint_types_from_db()
        _maint_types_cache = rows
        _maint_type_codes_cache = {r["code"] for r in rows if r["is_active"]}
        return _maint_types_cache
    except Exception as exc:
        logger.warning(
            f"catalog_cache: no se pudo cargar maint_types desde BD ({exc!r}); usando fallback"
        )
        return []


def get_maint_types(db=None) -> list:
    """
    Retorna todos los tipos de mantenimiento ordenados por display_order.
    `db` se acepta por compatibilidad pero no se usa.
    """
    rows = _ensure_maint_types_cache()
    if rows:
        return rows
    # Fallback mínimo cuando la BD no está disponible
    return [
        {"id": None, "code": c, "label": c.capitalize(),
         "display_order": i, "is_active": True}
        for i, c in enumerate(sorted(_FALLBACK_MAINT_TYPE_CODES))
    ]


def get_maint_type_codes(db=None) -> set:
    """
    Retorna el set de codes ACTIVOS de tipos de mantenimiento.
    Fallback: {'PREVENTIVO', 'CORRECTIVO'}.
    """
    _ensure_maint_types_cache()
    if _maint_type_codes_cache is not None:
        return _maint_type_codes_cache
    return set(_FALLBACK_MAINT_TYPE_CODES)


def invalidate_maint_types() -> None:
    """Limpia el cache de tipos de mantenimiento para que se recargue."""
    global _maint_types_cache, _maint_type_codes_cache
    _maint_types_cache = None
    _maint_type_codes_cache = None
    logger.debug("catalog_cache: cache de maint_types invalidado")


# ==================== SERVICE ORIGINS ====================

_service_origins_cache: Optional[list] = None
_service_origin_codes_cache: Optional[set] = None

_FALLBACK_SERVICE_ORIGIN_CODES = {'INTERNO', 'EXTERNO'}


def _load_service_origins_from_db() -> list:
    """
    Abre una sesión efímera, consulta maint_service_origin, cierra la sesión.
    Retorna lista de dicts ordenada por display_order.
    Lanza excepción si falla (el caller hace el try/except).
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.maint.models.simple_catalog import MaintServiceOrigin

    db = SessionLocal()
    try:
        rows = (
            db.query(MaintServiceOrigin)
            .order_by(MaintServiceOrigin.display_order)
            .all()
        )
        return [_service_origin_to_dict(r) for r in rows]
    finally:
        db.close()


def _service_origin_to_dict(s) -> dict:
    return {
        "id": s.id,
        "code": s.code,
        "label": s.label,
        "display_order": s.display_order,
        "is_active": s.is_active,
    }


def _ensure_service_origins_cache() -> list:
    """Rellena el cache si está vacío. Degrada silenciosamente si la BD falla."""
    global _service_origins_cache, _service_origin_codes_cache

    if _service_origins_cache is not None:
        return _service_origins_cache

    try:
        rows = _load_service_origins_from_db()
        _service_origins_cache = rows
        _service_origin_codes_cache = {r["code"] for r in rows if r["is_active"]}
        return _service_origins_cache
    except Exception as exc:
        logger.warning(
            f"catalog_cache: no se pudo cargar service_origins desde BD ({exc!r}); usando fallback"
        )
        return []


def get_service_origins(db=None) -> list:
    """
    Retorna todos los orígenes de servicio ordenados por display_order.
    `db` se acepta por compatibilidad pero no se usa.
    """
    rows = _ensure_service_origins_cache()
    if rows:
        return rows
    # Fallback mínimo cuando la BD no está disponible
    return [
        {"id": None, "code": c, "label": c.capitalize(),
         "display_order": i, "is_active": True}
        for i, c in enumerate(sorted(_FALLBACK_SERVICE_ORIGIN_CODES))
    ]


def get_service_origin_codes(db=None) -> set:
    """
    Retorna el set de codes ACTIVOS de orígenes de servicio.
    Fallback: {'INTERNO', 'EXTERNO'}.
    """
    _ensure_service_origins_cache()
    if _service_origin_codes_cache is not None:
        return _service_origin_codes_cache
    return set(_FALLBACK_SERVICE_ORIGIN_CODES)


def invalidate_service_origins() -> None:
    """Limpia el cache de orígenes de servicio para que se recargue."""
    global _service_origins_cache, _service_origin_codes_cache
    _service_origins_cache = None
    _service_origin_codes_cache = None
    logger.debug("catalog_cache: cache de service_origins invalidado")


# ==================== AREAS ====================

_areas_cache: Optional[list] = None
_area_codes_cache: Optional[set] = None

_FALLBACK_AREA_CODES = {
    'TRANSPORT', 'ELECTRICAL', 'CARPENTRY', 'AC', 'GARDENING', 'GENERAL', 'PAINTING',
}


def _load_areas_from_db() -> list:
    """
    Abre una sesión efímera, consulta maint_area, cierra la sesión.
    Retorna lista de dicts ordenada por display_order.
    Lanza excepción si falla (el caller hace el try/except).
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.maint.models.area import MaintArea

    db = SessionLocal()
    try:
        rows = (
            db.query(MaintArea)
            .order_by(MaintArea.display_order)
            .all()
        )
        return [_area_to_dict(r) for r in rows]
    finally:
        db.close()


def _area_to_dict(a) -> dict:
    return {
        "id": a.id,
        "code": a.code,
        "label": a.label,
        "icon": a.icon,
        "color": a.color,
        "description": a.description,
        "display_order": a.display_order,
        "is_active": a.is_active,
    }


def _ensure_areas_cache() -> list:
    """Rellena el cache si está vacío. Degrada silenciosamente si la BD falla."""
    global _areas_cache, _area_codes_cache

    if _areas_cache is not None:
        return _areas_cache

    try:
        rows = _load_areas_from_db()
        _areas_cache = rows
        _area_codes_cache = {r["code"] for r in rows if r["is_active"]}
        return _areas_cache
    except Exception as exc:
        logger.warning(
            f"catalog_cache: no se pudo cargar areas desde BD ({exc!r}); usando fallback"
        )
        return []


def get_areas(db=None) -> list:
    """
    Retorna todas las áreas técnicas ordenadas por display_order como lista de dicts.
    `db` se acepta por compatibilidad pero no se usa (el cache usa sesión efímera propia).
    Fallback defensivo si BD/tabla falla.
    """
    rows = _ensure_areas_cache()
    if rows:
        return rows
    # Fallback mínimo cuando la BD no está disponible
    return [
        {
            "id": None,
            "code": c,
            "label": c.capitalize(),
            "icon": None,
            "color": None,
            "description": None,
            "display_order": i,
            "is_active": True,
        }
        for i, c in enumerate(sorted(_FALLBACK_AREA_CODES))
    ]


def get_area_codes(db=None) -> set:
    """
    Retorna el set de codes ACTIVOS de áreas técnicas.
    Fallback: {'TRANSPORT','ELECTRICAL','CARPENTRY','AC','GARDENING','GENERAL','PAINTING'}.
    """
    _ensure_areas_cache()
    if _area_codes_cache is not None:
        return _area_codes_cache
    return set(_FALLBACK_AREA_CODES)


def get_area_by_code(code: str, db=None) -> Optional[dict]:
    """
    Retorna el dict del área con el code indicado, o None si no existe.
    Busca en el cache (cargando si es necesario); no lanza excepción.
    """
    try:
        rows = _ensure_areas_cache()
        for row in rows:
            if row["code"] == code:
                return row
    except Exception as exc:
        logger.warning(f"catalog_cache: error buscando área '{code}' ({exc!r})")
    return None


def invalidate_areas() -> None:
    """Limpia el cache de áreas para que se recargue en el siguiente acceso."""
    global _areas_cache, _area_codes_cache
    _areas_cache = None
    _area_codes_cache = None
    logger.debug("catalog_cache: cache de areas invalidado")


# ==================== NOTIFICATION TEMPLATES ====================

_notification_templates_cache: Optional[list] = None


def _load_notification_templates_from_db() -> list:
    """
    Abre una sesión efímera, consulta maint_notification_template, cierra la sesión.
    Retorna lista de dicts (todas, activas e inactivas) ordenada por id.
    Lanza excepción si falla (el caller hace el try/except).
    """
    from itcj2.database import SessionLocal
    from itcj2.apps.maint.models.notification_template import MaintNotificationTemplate

    db = SessionLocal()
    try:
        rows = db.query(MaintNotificationTemplate).order_by(MaintNotificationTemplate.id).all()
        return [_notification_template_to_dict(r) for r in rows]
    finally:
        db.close()


def _notification_template_to_dict(t) -> dict:
    return {
        "id": t.id,
        "code": t.code,
        "name": t.name,
        "channel": t.channel,
        "subject_template": t.subject_template,
        "title_template": t.title_template,
        "body_template": t.body_template,
        "variables": t.variables,
        "is_active": t.is_active,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "updated_by_id": t.updated_by_id,
    }


def _ensure_notification_templates_cache() -> list:
    """Rellena el cache si está vacío. Degrada silenciosamente si la BD falla."""
    global _notification_templates_cache

    if _notification_templates_cache is not None:
        return _notification_templates_cache

    try:
        rows = _load_notification_templates_from_db()
        _notification_templates_cache = rows
        return _notification_templates_cache
    except Exception as exc:
        logger.warning(
            f"catalog_cache: no se pudo cargar notification_templates desde BD ({exc!r}); sin plantillas"
        )
        return []


def get_notification_template(code: str, db=None) -> Optional[dict]:
    """
    Retorna el dict de la plantilla con el code indicado, solo si está activa.
    Retorna None si la plantilla no existe, está inactiva, o la BD falla.
    `db` se acepta por compatibilidad pero no se usa (sesión efímera propia).
    Nunca lanza excepción.
    """
    try:
        rows = _ensure_notification_templates_cache()
        for row in rows:
            if row["code"] == code:
                if row["is_active"]:
                    return row
                return None
    except Exception as exc:
        logger.warning(f"catalog_cache: error buscando notification_template '{code}' ({exc!r})")
    return None


def get_notification_templates(db=None) -> list:
    """
    Retorna todas las plantillas (activas e inactivas) como lista de dicts.
    Retorna [] si la BD falla.
    `db` se acepta por compatibilidad pero no se usa.
    Nunca lanza excepción.
    """
    try:
        return _ensure_notification_templates_cache()
    except Exception as exc:
        logger.warning(f"catalog_cache: error cargando notification_templates ({exc!r})")
        return []


def invalidate_notification_templates() -> None:
    """Limpia el cache de plantillas de notificación para que se recargue en el siguiente acceso."""
    global _notification_templates_cache
    _notification_templates_cache = None
    logger.debug("catalog_cache: cache de notification_templates invalidado")
