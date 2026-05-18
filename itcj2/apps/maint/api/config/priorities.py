"""
Config API — Prioridades (maint).

CRUD completo para el catálogo MaintPriority con auditoría en MaintConfigChangeLog
e invalidación del cache de módulo tras cada escritura.

Rutas reales (montado en /api/maint/v2/config/priorities):
  GET    /              → lista todas las prioridades
  POST   /              → crea nueva prioridad
  PATCH  /{pid}         → actualiza parcialmente (sin cambiar code)
  PATCH  /{pid}/toggle  → activa/desactiva
  PUT    /reorder       → reordena el listado
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.maint.schemas.config.priorities import (
    CreatePriority,
    UpdatePriority,
    TogglePriority,
    ReorderPriorities,
)
from itcj2.apps.maint.services.config_audit_service import log_config_change, client_ip
from itcj2.apps.maint.utils.catalog_cache import invalidate_priorities

router = APIRouter(tags=["maint-config-priorities"])
logger = logging.getLogger(__name__)


# ==================== HELPERS ====================

def _priority_to_dict(p) -> dict:
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


def _unmark_defaults(db: Session) -> None:
    """Desmarca todas las prioridades default (para imponer solo una)."""
    from itcj2.apps.maint.models.priority import MaintPriority
    db.query(MaintPriority).filter(
        MaintPriority.is_default == True  # noqa: E712
    ).update({"is_default": False}, synchronize_session="fetch")


# ==================== ENDPOINTS ====================

@router.get("")
def list_priorities(
    request: Request,
    user: dict = require_perms("maint", [
        "maint.config.priorities.api.read",
        "maint.admin.api.categories",      # admins de config general también ven
    ]),
    db: DbSession = None,
):
    """Lista todas las prioridades ordenadas por display_order."""
    from itcj2.apps.maint.models.priority import MaintPriority

    priorities = (
        db.query(MaintPriority)
        .order_by(MaintPriority.display_order)
        .all()
    )
    return {
        "success": True,
        "data": [_priority_to_dict(p) for p in priorities],
        "total": len(priorities),
    }


@router.post("", status_code=201)
def create_priority(
    request: Request,
    body: CreatePriority,
    user: dict = require_perms("maint", ["maint.config.priorities.api.update"]),
    db: DbSession = None,
):
    """Crea una nueva prioridad. code debe ser único (se normaliza a UPPER)."""
    from itcj2.apps.maint.models.priority import MaintPriority

    # Verificar unicidad de code
    existing = db.query(MaintPriority).filter(
        MaintPriority.code == body.code
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Ya existe una prioridad con code '{body.code}'")

    # Si es default, desmarcar las demás antes de insertar
    if body.is_default:
        _unmark_defaults(db)

    priority = MaintPriority(
        code=body.code,
        label=body.label,
        color=body.color,
        badge_class=body.badge_class,
        sla_hours=body.sla_hours,
        is_default=body.is_default or False,
        display_order=body.display_order if body.display_order is not None else 0,
        is_active=True,
    )
    db.add(priority)
    db.flush()   # Obtener el id antes del commit

    after = _priority_to_dict(priority)
    log_config_change(
        db=db,
        user_id=int(user["sub"]),
        entity_type="priority",
        entity_id=priority.id,
        action="create",
        before=None,
        after=after,
        ip=client_ip(request),
    )

    try:
        db.commit()
        db.refresh(priority)
        invalidate_priorities()
        logger.info(f"Prioridad '{priority.code}' creada por usuario {user['sub']}")
        return {"success": True, "data": _priority_to_dict(priority)}
    except Exception as exc:
        db.rollback()
        logger.error(f"Error creando prioridad: {exc!r}")
        raise HTTPException(status_code=500, detail="Error interno al crear prioridad")


@router.patch("/{pid}")
def update_priority(
    pid: int,
    request: Request,
    body: UpdatePriority,
    user: dict = require_perms("maint", ["maint.config.priorities.api.update"]),
    db: DbSession = None,
):
    """Actualiza parcialmente una prioridad. El campo `code` nunca se modifica."""
    from itcj2.apps.maint.models.priority import MaintPriority

    priority = db.get(MaintPriority, pid)
    if not priority:
        raise HTTPException(status_code=404, detail="Prioridad no encontrada")

    before = _priority_to_dict(priority)

    # Si se activa is_default, desmarcar el resto primero
    if body.is_default is True:
        _unmark_defaults(db)

    updates = body.model_dump(exclude_none=True)
    for key, val in updates.items():
        setattr(priority, key, val)

    after = _priority_to_dict(priority)
    log_config_change(
        db=db,
        user_id=int(user["sub"]),
        entity_type="priority",
        entity_id=pid,
        action="update",
        before=before,
        after=after,
        ip=client_ip(request),
    )

    try:
        db.commit()
        db.refresh(priority)
        invalidate_priorities()
        logger.info(f"Prioridad {pid} actualizada por usuario {user['sub']}")
        return {"success": True, "data": _priority_to_dict(priority)}
    except Exception as exc:
        db.rollback()
        logger.error(f"Error actualizando prioridad {pid}: {exc!r}")
        raise HTTPException(status_code=500, detail="Error interno al actualizar prioridad")


@router.patch("/{pid}/toggle")
def toggle_priority(
    pid: int,
    request: Request,
    body: TogglePriority,
    user: dict = require_perms("maint", ["maint.config.priorities.api.update"]),
    db: DbSession = None,
):
    """Activa o desactiva una prioridad. No se puede desactivar la default ni la última activa."""
    from itcj2.apps.maint.models.priority import MaintPriority

    priority = db.get(MaintPriority, pid)
    if not priority:
        raise HTTPException(status_code=404, detail="Prioridad no encontrada")

    if not body.is_active:
        # Regla: no se puede desactivar la prioridad default
        if priority.is_default:
            raise HTTPException(
                status_code=400,
                detail="No se puede desactivar la prioridad marcada como predeterminada",
            )
        # Regla: debe quedar al menos una activa
        active_count = db.query(MaintPriority).filter(
            MaintPriority.is_active == True  # noqa: E712
        ).count()
        if active_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Debe existir al menos una prioridad activa",
            )

    before = _priority_to_dict(priority)
    priority.is_active = body.is_active
    after = _priority_to_dict(priority)

    log_config_change(
        db=db,
        user_id=int(user["sub"]),
        entity_type="priority",
        entity_id=pid,
        action="toggle",
        before=before,
        after=after,
        ip=client_ip(request),
    )

    try:
        db.commit()
        db.refresh(priority)
        invalidate_priorities()
        estado = "activada" if body.is_active else "desactivada"
        logger.info(f"Prioridad {pid} {estado} por usuario {user['sub']}")
        return {"success": True, "data": _priority_to_dict(priority)}
    except Exception as exc:
        db.rollback()
        logger.error(f"Error en toggle de prioridad {pid}: {exc!r}")
        raise HTTPException(status_code=500, detail="Error interno al cambiar estado de prioridad")


@router.put("/reorder")
def reorder_priorities(
    request: Request,
    body: ReorderPriorities,
    user: dict = require_perms("maint", ["maint.config.priorities.api.update"]),
    db: DbSession = None,
):
    """Reordena el catálogo de prioridades en bloque."""
    from itcj2.apps.maint.models.priority import MaintPriority

    if not body.order:
        raise HTTPException(status_code=400, detail="La lista de orden no puede estar vacía")

    before_snapshot = []
    for item in body.order:
        p = db.get(MaintPriority, item.id)
        if not p:
            raise HTTPException(status_code=404, detail=f"Prioridad con id={item.id} no encontrada")
        before_snapshot.append({"id": p.id, "code": p.code, "display_order": p.display_order})
        p.display_order = item.display_order

    after_snapshot = [{"id": i.id, "display_order": i.display_order} for i in body.order]

    log_config_change(
        db=db,
        user_id=int(user["sub"]),
        entity_type="priority",
        entity_id=None,
        action="reorder",
        before={"items": before_snapshot},
        after={"items": after_snapshot},
        ip=client_ip(request),
    )

    try:
        db.commit()
        invalidate_priorities()
        logger.info(f"Prioridades reordenadas por usuario {user['sub']}")
        return {"success": True}
    except Exception as exc:
        db.rollback()
        logger.error(f"Error reordenando prioridades: {exc!r}")
        raise HTTPException(status_code=500, detail="Error interno al reordenar prioridades")
