"""
Config API — Auditoría de cambios de configuración (maint).

Endpoints de solo lectura sobre MaintConfigChangeLog.
Export CSV se agrega en Fase 7.

Rutas reales (montado en /api/maint/v2/config/audit):
  GET /          → paginado con filtros opcionales
  GET /{log_id}  → detalle completo incluyendo before_data / after_data
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.orm import joinedload

from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["maint-config-audit"])
logger = logging.getLogger(__name__)


def _log_to_dict(entry, full: bool = False) -> dict:
    """Serializa una entrada de MaintConfigChangeLog."""
    result = {
        "id": entry.id,
        "user_id": entry.user_id,
        "user_name": (
            f"{entry.user.first_name} {entry.user.last_name}"
            if entry.user else str(entry.user_id)
        ),
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "action": entry.action,
        "changed_at": entry.changed_at.isoformat() if entry.changed_at else None,
        "ip_address": entry.ip_address,
    }
    if full:
        result["before_data"] = entry.before_data
        result["after_data"] = entry.after_data
    return result


@router.get("")
def list_audit_log(
    request: Request,
    entity_type: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    user_id: Optional[int] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="ISO date YYYY-MM-DD"),
    date_to: Optional[str] = Query(default=None, description="ISO date YYYY-MM-DD"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=100),
    user: dict = require_perms("maint", ["maint.config.audit.api.read"]),
    db: DbSession = None,
):
    """
    Lista el log de auditoría de configuración con filtros opcionales.
    Ordenado por changed_at DESC.
    """
    from itcj2.apps.maint.models.config_change_log import MaintConfigChangeLog

    query = (
        db.query(MaintConfigChangeLog)
        .options(joinedload(MaintConfigChangeLog.user))
    )

    if entity_type:
        query = query.filter(MaintConfigChangeLog.entity_type == entity_type)
    if action:
        query = query.filter(MaintConfigChangeLog.action == action)
    if user_id:
        query = query.filter(MaintConfigChangeLog.user_id == user_id)

    if date_from:
        try:
            from datetime import datetime
            dt_from = datetime.fromisoformat(date_from)
            query = query.filter(MaintConfigChangeLog.changed_at >= dt_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="date_from inválido, formato esperado: YYYY-MM-DD")

    if date_to:
        try:
            from datetime import datetime, timedelta
            dt_to = datetime.fromisoformat(date_to) + timedelta(days=1)
            query = query.filter(MaintConfigChangeLog.changed_at < dt_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="date_to inválido, formato esperado: YYYY-MM-DD")

    query = query.order_by(MaintConfigChangeLog.changed_at.desc())

    total = query.count()
    offset = (page - 1) * per_page
    items = query.offset(offset).limit(per_page).all()

    total_pages = max(1, (total + per_page - 1) // per_page)

    return {
        "success": True,
        "data": [_log_to_dict(e) for e in items],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


@router.get("/{log_id}")
def get_audit_log_detail(
    log_id: int,
    request: Request,
    user: dict = require_perms("maint", ["maint.config.audit.api.read"]),
    db: DbSession = None,
):
    """Detalle completo de una entrada de auditoría, incluyendo before_data y after_data."""
    from itcj2.apps.maint.models.config_change_log import MaintConfigChangeLog

    entry = (
        db.query(MaintConfigChangeLog)
        .options(joinedload(MaintConfigChangeLog.user))
        .filter(MaintConfigChangeLog.id == log_id)
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Entrada de auditoría no encontrada")

    return {"success": True, "data": _log_to_dict(entry, full=True)}
