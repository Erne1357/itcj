"""
Servicio de auditoría para cambios de configuración del módulo Helpdesk.
Registra snapshots before/after en la tabla helpdesk_config_change_log.
"""
import logging
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def log_config_change(
    db: Session,
    user_id: int,
    entity_type: str,
    entity_id: int | None,
    action: str,
    before: dict | None = None,
    after: dict | None = None,
    ip_address: str | None = None,
):
    """
    Registra un cambio de configuración. NO commitea — el caller decide cuándo.

    Parámetros:
        db          -- sesión SQLAlchemy activa
        user_id     -- id del usuario que realizó la acción
        entity_type -- entidad modificada: category|priority|status|area|notification|field_template
        entity_id   -- id del registro modificado (None en operaciones bulk/reorder)
        action      -- tipo de operación: create|update|delete|toggle|reorder
        before      -- snapshot del estado anterior (None en create)
        after       -- snapshot del estado posterior (None en delete)
        ip_address  -- IP del cliente (IPv4 o IPv6)

    Retorna la instancia ConfigChangeLog ya agregada a la sesión pero no commiteada.
    """
    from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

    log = ConfigChangeLog(
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        before_data=before,
        after_data=after,
        ip_address=ip_address,
    )
    db.add(log)
    logger.debug(
        f"config_audit: {action} {entity_type}#{entity_id} por user_id={user_id}"
    )
    return log
