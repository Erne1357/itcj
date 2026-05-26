"""
Config API — Auditoría de cambios de configuración (maint).

Endpoints de solo lectura sobre MaintConfigChangeLog.

Rutas reales (montado en /api/maint/v2/config/audit):
  GET /              → paginado con filtros opcionales
  GET /export.csv    → descarga CSV con todos los registros (límite 50 000 filas)
  GET /{log_id}      → detalle completo incluyendo before_data / after_data
"""
import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
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


_CSV_LIMIT = 50_000
_CSV_COLUMNS = [
    "id",
    "changed_at",
    "user_id",
    "user_name",
    "entity_type",
    "entity_id",
    "action",
    "ip_address",
    "before_data",
    "after_data",
]


@router.get("/export.csv")
def export_audit_csv(
    request: Request,
    entity_type: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    user_id: Optional[int] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="ISO date YYYY-MM-DD"),
    date_to: Optional[str] = Query(default=None, description="ISO date YYYY-MM-DD"),
    user: dict = require_perms("maint", [
        "maint.config.audit.api.read",
        "maint.admin.api.categories",
    ]),
    db: DbSession = None,
):
    """
    Exporta el log de auditoría como CSV (BOM UTF-8 para Excel).

    Mismos filtros que el list paginado pero sin paginación.
    Límite duro: 50 000 filas, orden changed_at DESC.
    Columnas: id, changed_at, user_id, user_name, entity_type, entity_id,
              action, ip_address, before_data (JSON), after_data (JSON).
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
            dt_from = datetime.fromisoformat(date_from)
            query = query.filter(MaintConfigChangeLog.changed_at >= dt_from)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="date_from inválido, formato esperado: YYYY-MM-DD",
            )

    if date_to:
        try:
            from datetime import timedelta
            dt_to = datetime.fromisoformat(date_to) + timedelta(days=1)
            query = query.filter(MaintConfigChangeLog.changed_at < dt_to)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="date_to inválido, formato esperado: YYYY-MM-DD",
            )

    query = query.order_by(MaintConfigChangeLog.changed_at.desc()).limit(_CSV_LIMIT)
    entries = query.all()

    # Construir CSV en memoria con BOM UTF-8 para compatibilidad con Excel
    buf = io.StringIO()
    buf.write("﻿")  # BOM UTF-8
    writer = csv.writer(buf, dialect="excel")
    writer.writerow(_CSV_COLUMNS)

    for e in entries:
        user_name = (
            f"{e.user.first_name} {e.user.last_name}"
            if e.user else str(e.user_id)
        )
        before_str = json.dumps(e.before_data, ensure_ascii=False) if e.before_data is not None else ""
        after_str = json.dumps(e.after_data, ensure_ascii=False) if e.after_data is not None else ""
        changed_at_str = e.changed_at.isoformat() if e.changed_at else ""

        writer.writerow([
            e.id,
            changed_at_str,
            e.user_id,
            user_name,
            e.entity_type,
            e.entity_id if e.entity_id is not None else "",
            e.action,
            e.ip_address or "",
            before_str,
            after_str,
        ])

    csv_bytes = buf.getvalue().encode("utf-8")
    now_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"maint_config_audit_{now_str}.csv"

    logger.info(
        "Audit CSV exportado por usuario %s — %d filas, filtros: entity_type=%s action=%s user_id=%s date_from=%s date_to=%s",
        user["sub"], len(entries), entity_type, action, user_id, date_from, date_to,
    )

    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
