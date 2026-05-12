"""
Cache in-memory de catálogos de configuración con invalidación manual.

No usa TTL porque la invalidación se realiza explícitamente al modificar
un registro en la API. El cache es por proceso: en entornos con múltiples
workers (gunicorn, uvicorn multiprocess) cada worker mantiene su propio
cache. La invalidación es best-effort — si un worker actualiza el catálogo
sólo invalida su copia local. Bajo carga normal esto es aceptable dado que
las prioridades y estados cambian raramente.
"""
import logging
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ==================== PRIORIDADES ====================

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


# ==================== ESTADOS (TicketStatus) ====================

_STATUSES_BY_CODE: dict[str, dict] | None = None


def _ensure_statuses_loaded(db: Session) -> None:
    """Carga el cache de estados desde BD si aún no está poblado."""
    global _STATUSES_BY_CODE
    if _STATUSES_BY_CODE is None:
        from itcj2.apps.helpdesk.models.ticket_status import TicketStatus
        rows = db.query(TicketStatus).order_by(TicketStatus.display_order).all()
        _STATUSES_BY_CODE = {s.code: s.to_dict() for s in rows}
        logger.debug(f"catalog_cache: cargados {len(_STATUSES_BY_CODE)} estados")


def get_statuses(db: Session, active_only: bool = True) -> list[dict]:
    """Devuelve lista de estados ordenada por display_order."""
    _ensure_statuses_loaded(db)
    items = list(_STATUSES_BY_CODE.values())
    if active_only:
        items = [s for s in items if s.get("is_active")]
    return items


def get_status_by_code(db: Session, code: str) -> dict | None:
    """Lookup individual por code. Devuelve None si no existe."""
    _ensure_statuses_loaded(db)
    return _STATUSES_BY_CODE.get(code)


def get_status_codes(db: Session, active_only: bool = True) -> set[str]:
    """Conjunto de codes válidos. Útil para validación rápida."""
    _ensure_statuses_loaded(db)
    if active_only:
        return {code for code, s in _STATUSES_BY_CODE.items() if s.get("is_active")}
    return set(_STATUSES_BY_CODE.keys())


def get_status_flags(status_code: str) -> dict | None:
    """
    Lookup de flags sin requerir db como parámetro.
    Usa el cache existente. Si el cache no está poblado, abre una sesión efímera.
    Diseñado para uso en propiedades del modelo Ticket donde no hay db disponible.
    """
    global _STATUSES_BY_CODE
    if _STATUSES_BY_CODE is None:
        from itcj2.database import SessionLocal
        db = SessionLocal()
        try:
            _ensure_statuses_loaded(db)
        finally:
            db.close()
    return _STATUSES_BY_CODE.get(status_code) if _STATUSES_BY_CODE else None


def invalidate_statuses() -> None:
    """Limpia el cache de estados. Debe llamarse tras cualquier operación write."""
    global _STATUSES_BY_CODE
    _STATUSES_BY_CODE = None
    logger.debug("catalog_cache: cache de estados invalidado")


# ==================== TRANSICIONES (StatusTransition) ====================

_TRANSITIONS_BY_FROM_CODE: dict[str, set[str]] | None = None
# Índice secundario: (from_code, to_code) -> dict completo de la transición
_TRANSITIONS_FULL: dict[tuple[str, str], dict] | None = None


def _ensure_transitions_loaded(db: Session) -> None:
    """Carga el cache de transiciones activas desde BD si aún no está poblado."""
    global _TRANSITIONS_BY_FROM_CODE, _TRANSITIONS_FULL
    if _TRANSITIONS_BY_FROM_CODE is None:
        from itcj2.apps.helpdesk.models.status_transition import StatusTransition
        rows = db.query(StatusTransition).filter_by(is_active=True).all()
        idx: dict[str, set[str]] = {}
        full: dict[tuple[str, str], dict] = {}
        for t in rows:
            from_code = t.from_status.code if t.from_status else None
            to_code = t.to_status.code if t.to_status else None
            if from_code and to_code:
                idx.setdefault(from_code, set()).add(to_code)
                full[(from_code, to_code)] = t.to_dict(include_status_codes=True)
        _TRANSITIONS_BY_FROM_CODE = idx
        _TRANSITIONS_FULL = full
        logger.debug(f"catalog_cache: cargadas {len(full)} transiciones")


def get_allowed_transitions(db: Session, from_code: str) -> set[str]:
    """Devuelve el conjunto de códigos de destino permitidos desde from_code."""
    _ensure_transitions_loaded(db)
    return set(_TRANSITIONS_BY_FROM_CODE.get(from_code, set()))


def is_transition_allowed(db: Session, from_code: str, to_code: str) -> bool:
    """
    Valida si la transición from_code → to_code está permitida.
    Permite from == to sin consultar BD (no-op aceptado).
    """
    if from_code == to_code:
        return True
    _ensure_transitions_loaded(db)
    return to_code in _TRANSITIONS_BY_FROM_CODE.get(from_code, set())


def get_transition_record(db: Session, from_code: str, to_code: str) -> dict | None:
    """
    Devuelve el registro completo de la transición, incluyendo required_perm
    y required_fields. Útil para validaciones más finas en el service.
    """
    _ensure_transitions_loaded(db)
    return _TRANSITIONS_FULL.get((from_code, to_code)) if _TRANSITIONS_FULL else None


def invalidate_transitions() -> None:
    """Limpia el cache de transiciones. Debe llamarse tras cualquier operación write."""
    global _TRANSITIONS_BY_FROM_CODE, _TRANSITIONS_FULL
    _TRANSITIONS_BY_FROM_CODE = None
    _TRANSITIONS_FULL = None
    logger.debug("catalog_cache: cache de transiciones invalidado")


# ==================== AREAS ====================

_AREAS_BY_CODE: dict[str, dict] | None = None

# Fallback defensivo usado cuando la BD es inalcanzable o el cache está vacío.
_AREAS_FALLBACK: set[str] = {"DESARROLLO", "SOPORTE"}


def _ensure_areas_loaded(db: Session) -> None:
    """Carga el cache de áreas desde BD si aún no está poblado."""
    global _AREAS_BY_CODE
    if _AREAS_BY_CODE is None:
        from itcj2.apps.helpdesk.models.area import Area
        rows = db.query(Area).order_by(Area.display_order).all()
        _AREAS_BY_CODE = {a.code: a.to_dict() for a in rows}
        logger.debug(f"catalog_cache: cargadas {len(_AREAS_BY_CODE)} áreas")


def get_areas(db: Session, active_only: bool = True) -> list[dict]:
    """Devuelve lista de áreas ordenada por display_order."""
    _ensure_areas_loaded(db)
    items = list(_AREAS_BY_CODE.values())
    if active_only:
        items = [a for a in items if a.get("is_active")]
    return items


def get_area_by_code(db: Session, code: str) -> dict | None:
    """Lookup individual por code. Devuelve None si no existe."""
    _ensure_areas_loaded(db)
    return _AREAS_BY_CODE.get(code)


def get_area_codes(db: Session = None, active_only: bool = True) -> set[str]:
    """
    Conjunto de codes válidos. Útil para validación rápida en endpoints.
    Fallback defensivo: si la BD es inalcanzable o el cache queda vacío,
    devuelve {'DESARROLLO', 'SOPORTE'} para no romper flujos existentes.
    """
    try:
        _ensure_areas_loaded(db)
        if not _AREAS_BY_CODE:
            return _AREAS_FALLBACK.copy()
        if active_only:
            return {code for code, a in _AREAS_BY_CODE.items() if a.get("is_active")}
        return set(_AREAS_BY_CODE.keys())
    except Exception:
        logger.warning("catalog_cache: get_area_codes falló, usando fallback defensivo")
        return _AREAS_FALLBACK.copy()


def invalidate_areas() -> None:
    """Limpia el cache de áreas. Debe llamarse tras cualquier operación write."""
    global _AREAS_BY_CODE
    _AREAS_BY_CODE = None
    logger.debug("catalog_cache: cache de áreas invalidado")


# ==================== NOTIFICATION TEMPLATES ====================

_NOTIFICATION_TEMPLATES_BY_CODE: dict[str, dict] | None = None


def _ensure_notification_templates_loaded(db: Session) -> None:
    """Carga el cache de plantillas de notificación desde BD si aún no está poblado."""
    global _NOTIFICATION_TEMPLATES_BY_CODE
    if _NOTIFICATION_TEMPLATES_BY_CODE is None:
        from itcj2.apps.helpdesk.models.notification_template import NotificationTemplate
        rows = db.query(NotificationTemplate).all()
        _NOTIFICATION_TEMPLATES_BY_CODE = {t.code: t.to_dict() for t in rows}
        logger.debug(
            f"catalog_cache: cargadas {len(_NOTIFICATION_TEMPLATES_BY_CODE)} plantillas de notificación"
        )


def get_notification_template(db: Session, code: str) -> dict | None:
    """
    Lookup por code. Devuelve None si la plantilla no existe O si está
    marcada is_active=False, para que el helper use el fallback hardcoded.
    """
    _ensure_notification_templates_loaded(db)
    entry = _NOTIFICATION_TEMPLATES_BY_CODE.get(code)
    if entry is None:
        return None
    return entry if entry.get("is_active") else None


def get_notification_templates(db: Session, active_only: bool = True) -> list[dict]:
    """Devuelve lista de todas las plantillas, opcionalmente filtradas por is_active."""
    _ensure_notification_templates_loaded(db)
    items = list(_NOTIFICATION_TEMPLATES_BY_CODE.values())
    if active_only:
        items = [t for t in items if t.get("is_active")]
    return items


def invalidate_notification_templates() -> None:
    """Limpia el cache de plantillas. Debe llamarse tras cualquier operación write."""
    global _NOTIFICATION_TEMPLATES_BY_CODE
    _NOTIFICATION_TEMPLATES_BY_CODE = None
    logger.debug("catalog_cache: cache de plantillas de notificación invalidado")
