"""
API de auditoría de cambios de configuración del Helpdesk (solo lectura).
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["helpdesk-config-audit"])
logger = logging.getLogger(__name__)


@router.get("")
def list_audit_logs(
    entity_type: Optional[str] = Query(default=None),
    entity_id: Optional[int] = Query(default=None),
    action: Optional[str] = Query(default=None),
    user_id: Optional[int] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    user: dict = require_perms("helpdesk", ["helpdesk.config.audit.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

    query = db.query(ConfigChangeLog)

    if entity_type:
        query = query.filter(ConfigChangeLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(ConfigChangeLog.entity_id == entity_id)
    if action:
        query = query.filter(ConfigChangeLog.action == action)
    if user_id is not None:
        query = query.filter(ConfigChangeLog.user_id == user_id)

    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            query = query.filter(ConfigChangeLog.changed_at >= dt_from)
        except ValueError:
            raise HTTPException(400, detail={
                "error": "invalid_date_from",
                "message": "date_from debe ser formato ISO 8601 (ej: 2026-01-01 o 2026-01-01T00:00:00)",
            })

    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            query = query.filter(ConfigChangeLog.changed_at <= dt_to)
        except ValueError:
            raise HTTPException(400, detail={
                "error": "invalid_date_to",
                "message": "date_to debe ser formato ISO 8601",
            })

    query = query.order_by(ConfigChangeLog.changed_at.desc())

    total = query.count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    offset = (page - 1) * per_page
    logs = query.offset(offset).limit(per_page).all()

    return {
        "logs": [_log_to_dict(log) for log in logs],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": total_pages,
    }


@router.get("/{log_id}")
def get_audit_log(
    log_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.config.audit.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.config_change_log import ConfigChangeLog

    log = db.get(ConfigChangeLog, log_id)
    if not log:
        raise HTTPException(404, detail={"error": "not_found", "message": "Registro de auditoría no encontrado"})

    return {"log": _log_to_dict(log, include_user=True)}


def _log_to_dict(log, include_user: bool = True) -> dict:
    """Serializa un ConfigChangeLog incluyendo datos del usuario si la relación está cargada."""
    data = log.to_dict(include_user=False)

    if include_user and log.user:
        full_name = getattr(log.user, "full_name", None) or str(log.user_id)
        data["user"] = {"id": log.user.id, "full_name": full_name}
    elif include_user:
        data["user"] = {"id": log.user_id, "full_name": str(log.user_id)}

    return data
