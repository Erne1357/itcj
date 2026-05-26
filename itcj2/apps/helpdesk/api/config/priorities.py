"""
API CRUD de prioridades de configuración del Helpdesk.
Espejo de itcj2/apps/helpdesk/api/categories.py con auditoría adicional.
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.helpdesk.schemas.config.priorities import (
    CreatePriorityRequest,
    UpdatePriorityRequest,
    TogglePriorityRequest,
    ReorderPrioritiesRequest,
)

router = APIRouter(tags=["helpdesk-config-priorities"])
logger = logging.getLogger(__name__)


@router.get("")
def list_priorities(
    include_inactive: str = "false",
    user: dict = require_perms("helpdesk", ["helpdesk.config.priorities.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.priority import Priority

    query = db.query(Priority)
    if include_inactive.lower() != "true":
        query = query.filter_by(is_active=True)

    priorities = query.order_by(Priority.display_order).all()
    return {"priorities": [p.to_dict() for p in priorities], "total": len(priorities)}


@router.get("/{priority_id}")
def get_priority(
    priority_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.config.priorities.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.priority import Priority

    priority = db.get(Priority, priority_id)
    if not priority:
        raise HTTPException(404, detail={"error": "not_found", "message": "Prioridad no encontrada"})

    return {"priority": priority.to_dict()}


@router.post("", status_code=201)
def create_priority(
    body: CreatePriorityRequest,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.priorities.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.priority import Priority
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_priorities
    from sqlalchemy import func

    user_id = int(user["sub"])
    code = body.code.strip().upper()

    existing = db.query(Priority).filter(
        func.upper(Priority.code) == code
    ).first()
    if existing:
        raise HTTPException(409, detail={
            "error": "code_exists",
            "message": f'Ya existe una prioridad con el código "{code}"',
        })

    if body.display_order is None:
        max_order = db.query(func.max(Priority.display_order)).scalar()
        display_order = (max_order or 0) + 1
    else:
        display_order = body.display_order

    priority = Priority(
        code=code,
        label=body.label.strip(),
        color=body.color,
        badge_class=body.badge_class,
        sla_hours=body.sla_hours,
        display_order=display_order,
        is_active=True,
    )
    db.add(priority)
    db.flush()  # obtener id antes del commit

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="priority",
        entity_id=priority.id,
        action="create",
        before=None,
        after=priority.to_dict(),
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(priority)
    invalidate_priorities()

    logger.info(f"Prioridad '{priority.code}' creada por usuario {user_id}")
    return {"message": "Prioridad creada exitosamente", "priority": priority.to_dict()}


@router.patch("/{priority_id}")
def update_priority(
    priority_id: int,
    body: UpdatePriorityRequest,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.priorities.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.priority import Priority
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_priorities

    user_id = int(user["sub"])
    priority = db.get(Priority, priority_id)
    if not priority:
        raise HTTPException(404, detail={"error": "not_found", "message": "Prioridad no encontrada"})

    before = priority.to_dict()

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(priority, field, value)

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="priority",
        entity_id=priority.id,
        action="update",
        before=before,
        after=priority.to_dict(),
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(priority)
    invalidate_priorities()

    logger.info(f"Prioridad {priority_id} actualizada por usuario {user_id}")
    return {"message": "Prioridad actualizada exitosamente", "priority": priority.to_dict()}


@router.post("/{priority_id}/toggle")
def toggle_priority(
    priority_id: int,
    body: TogglePriorityRequest,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.priorities.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.priority import Priority
    from itcj2.apps.helpdesk.models.ticket import Ticket
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_priorities

    user_id = int(user["sub"])
    priority = db.get(Priority, priority_id)
    if not priority:
        raise HTTPException(404, detail={"error": "not_found", "message": "Prioridad no encontrada"})

    if not body.is_active and priority.is_active:
        active_tickets = db.query(Ticket).filter(
            Ticket.priority == priority.code,
            Ticket.status.notin_(["CLOSED", "CANCELED"]),
        ).count()
        if active_tickets > 0:
            raise HTTPException(400, detail={
                "error": "has_active_tickets",
                "message": f"No se puede desactivar. Hay {active_tickets} ticket(s) activo(s) con esta prioridad",
                "active_tickets_count": active_tickets,
            })

    before = priority.to_dict()
    priority.is_active = body.is_active

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="priority",
        entity_id=priority.id,
        action="toggle",
        before=before,
        after=priority.to_dict(),
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(priority)
    invalidate_priorities()

    action_label = "activada" if body.is_active else "desactivada"
    logger.info(f"Prioridad {priority_id} {action_label} por usuario {user_id}")
    return {"message": f"Prioridad {action_label} exitosamente", "priority": priority.to_dict()}


@router.post("/reorder")
def reorder_priorities(
    body: ReorderPrioritiesRequest,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.priorities.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.priority import Priority
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_priorities

    user_id = int(user["sub"])

    before_snapshot = []
    for item in body.order:
        if "id" not in item or "display_order" not in item:
            raise HTTPException(400, detail={
                "error": "invalid_order_item",
                "message": "Cada item debe tener id y display_order",
            })
        p = db.get(Priority, item["id"])
        if not p:
            raise HTTPException(404, detail={
                "error": "priority_not_found",
                "message": f'Prioridad con id {item["id"]} no encontrada',
            })
        before_snapshot.append({"id": p.id, "code": p.code, "display_order": p.display_order})
        p.display_order = item["display_order"]

    after_snapshot = [{"id": item["id"], "display_order": item["display_order"]} for item in body.order]

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="priority",
        entity_id=None,
        action="reorder",
        before={"items": before_snapshot},
        after={"items": after_snapshot},
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    invalidate_priorities()

    priorities = db.query(Priority).order_by(Priority.display_order).all()
    logger.info(f"Prioridades reordenadas por usuario {user_id}")
    return {"message": "Orden actualizado exitosamente", "priorities": [p.to_dict() for p in priorities]}


@router.delete("/{priority_id}")
def delete_priority(
    priority_id: int,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.priorities.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.priority import Priority
    from itcj2.apps.helpdesk.models.ticket import Ticket
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_priorities

    user_id = int(user["sub"])
    priority = db.get(Priority, priority_id)
    if not priority:
        raise HTTPException(404, detail={"error": "not_found", "message": "Prioridad no encontrada"})

    tickets_count = db.query(Ticket).filter(Ticket.priority == priority.code).count()
    if tickets_count > 0:
        raise HTTPException(400, detail={
            "error": "has_tickets",
            "message": f"No se puede eliminar. Hay {tickets_count} ticket(s) asociado(s)",
            "tickets_count": tickets_count,
        })

    before = priority.to_dict()
    priority.is_active = False

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="priority",
        entity_id=priority.id,
        action="delete",
        before=before,
        after=priority.to_dict(),
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    invalidate_priorities()

    logger.info(f"Prioridad {priority_id} eliminada (soft delete) por usuario {user_id}")
    return {"message": "Prioridad eliminada exitosamente"}
