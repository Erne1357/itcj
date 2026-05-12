"""
API de estados de ticket — SOLO edición de metadata.
No permite crear ni borrar estados (decisión de producto).
Espejo de itcj2/apps/helpdesk/api/config/priorities.py.
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.helpdesk.schemas.config.statuses import (
    UpdateStatusRequest,
    ToggleStatusRequest,
    ReorderStatusesRequest,
)

router = APIRouter(tags=["helpdesk-config-statuses"])
logger = logging.getLogger(__name__)


@router.get("")
def list_statuses(
    include_inactive: str = "false",
    user: dict = require_perms("helpdesk", ["helpdesk.config.statuses.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.ticket_status import TicketStatus

    query = db.query(TicketStatus)
    if include_inactive.lower() != "true":
        query = query.filter_by(is_active=True)

    statuses = query.order_by(TicketStatus.display_order).all()
    return {"statuses": [s.to_dict() for s in statuses], "total": len(statuses)}


@router.get("/{status_id}")
def get_status(
    status_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.config.statuses.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.ticket_status import TicketStatus

    status = db.get(TicketStatus, status_id)
    if not status:
        raise HTTPException(404, detail={"error": "not_found", "message": "Estado no encontrado"})

    return {"status": status.to_dict()}


@router.patch("/{status_id}")
def update_status(
    status_id: int,
    body: UpdateStatusRequest,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.statuses.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.ticket_status import TicketStatus
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_statuses

    user_id = int(user["sub"])
    status = db.get(TicketStatus, status_id)
    if not status:
        raise HTTPException(404, detail={"error": "not_found", "message": "Estado no encontrado"})

    before = status.to_dict()

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(status, field, value)

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="status",
        entity_id=status.id,
        action="update",
        before=before,
        after=status.to_dict(),
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(status)
    invalidate_statuses()

    logger.info(f"Estado {status_id} ({status.code}) actualizado por usuario {user_id}")
    return {"message": "Estado actualizado exitosamente", "status": status.to_dict()}


@router.post("/{status_id}/toggle")
def toggle_status(
    status_id: int,
    body: ToggleStatusRequest,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.statuses.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.ticket_status import TicketStatus
    from itcj2.apps.helpdesk.models.ticket import Ticket
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_statuses

    user_id = int(user["sub"])
    status = db.get(TicketStatus, status_id)
    if not status:
        raise HTTPException(404, detail={"error": "not_found", "message": "Estado no encontrado"})

    # Prevenir desactivar un estado no-terminal con tickets activos
    if not body.is_active and status.is_active and not status.is_terminal:
        active_tickets = db.query(Ticket).filter(
            Ticket.status == status.code,
        ).count()
        if active_tickets > 0:
            raise HTTPException(400, detail={
                "error": "has_active_tickets",
                "message": (
                    f"No se puede desactivar. Hay {active_tickets} ticket(s) "
                    f"activo(s) en estado '{status.label}'"
                ),
                "active_tickets_count": active_tickets,
            })

    before = status.to_dict()
    status.is_active = body.is_active

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="status",
        entity_id=status.id,
        action="toggle",
        before=before,
        after=status.to_dict(),
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(status)
    invalidate_statuses()

    action_label = "activado" if body.is_active else "desactivado"
    logger.info(f"Estado {status_id} ({status.code}) {action_label} por usuario {user_id}")
    return {"message": f"Estado {action_label} exitosamente", "status": status.to_dict()}


@router.post("/reorder")
def reorder_statuses(
    body: ReorderStatusesRequest,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.statuses.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.ticket_status import TicketStatus
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_statuses

    user_id = int(user["sub"])

    before_snapshot = []
    for item in body.order:
        if "id" not in item or "display_order" not in item:
            raise HTTPException(400, detail={
                "error": "invalid_order_item",
                "message": "Cada item debe tener id y display_order",
            })
        s = db.get(TicketStatus, item["id"])
        if not s:
            raise HTTPException(404, detail={
                "error": "status_not_found",
                "message": f'Estado con id {item["id"]} no encontrado',
            })
        before_snapshot.append({"id": s.id, "code": s.code, "display_order": s.display_order})
        s.display_order = item["display_order"]

    after_snapshot = [{"id": item["id"], "display_order": item["display_order"]} for item in body.order]

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="status",
        entity_id=None,
        action="reorder",
        before={"items": before_snapshot},
        after={"items": after_snapshot},
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    invalidate_statuses()

    statuses = db.query(TicketStatus).order_by(TicketStatus.display_order).all()
    logger.info(f"Estados reordenados por usuario {user_id}")
    return {"message": "Orden actualizado exitosamente", "statuses": [s.to_dict() for s in statuses]}
