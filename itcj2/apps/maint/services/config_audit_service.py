"""
Servicio de auditoría para cambios de configuración del módulo maint.

Registra create/update/delete/toggle/reorder sobre entidades de configuración
(priority, category, field_template, etc.) en MaintConfigChangeLog.
El commit lo decide el caller.
"""
import logging
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def client_ip(request) -> Optional[str]:
    """
    Extrae la IP real del cliente desde el Request de FastAPI.
    Prioriza X-Forwarded-For (detrás de proxy/Nginx), luego client.host.
    Tolerante a request=None y a headers ausentes.
    """
    if request is None:
        return None
    try:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Tomar la primera IP de la cadena (IP del cliente original)
            return forwarded.split(",")[0].strip()
        if request.client and request.client.host:
            return request.client.host
    except Exception:
        pass
    return None


def log_config_change(
    db: Session,
    user_id: int,
    entity_type: str,
    entity_id: Optional[int],
    action: str,
    before: Optional[dict],
    after: Optional[dict],
    ip: Optional[str] = None,
) -> None:
    """
    Registra un cambio de configuración en MaintConfigChangeLog.

    NO hace commit — el caller es responsable de commitear.

    Args:
        db:          Sesión activa de SQLAlchemy.
        user_id:     ID del usuario que realizó el cambio (int, no str).
        entity_type: Tipo de entidad ('priority', 'category', 'field_template', etc.).
        entity_id:   ID numérico de la entidad afectada (None para reorder global).
        action:      Operación realizada ('create', 'update', 'toggle', 'reorder', 'delete').
        before:      Snapshot del estado anterior (None si es creación).
        after:       Snapshot del estado posterior (None si es eliminación).
        ip:          IP del cliente (resultado de client_ip(request)).
    """
    from itcj2.apps.maint.models.config_change_log import MaintConfigChangeLog

    try:
        log_entry = MaintConfigChangeLog(
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            before_data=before,
            after_data=after,
            ip_address=ip,
        )
        db.add(log_entry)
    except Exception as exc:
        # No propagar: la auditoría nunca debe romper la operación principal
        logger.error(f"config_audit_service: error registrando cambio ({entity_type}/{entity_id}/{action}): {exc!r}")
