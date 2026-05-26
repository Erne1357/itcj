"""
API de áreas del Helpdesk — SOLO edición de metadata.
No permite crear ni borrar áreas (decisión de producto).
Las áreas DESARROLLO y SOPORTE son fijas y están profundamente acopladas a la UI.
Espejo de itcj2/apps/helpdesk/api/config/statuses.py.
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.helpdesk.schemas.config.areas import (
    UpdateAreaRequest,
    ToggleAreaRequest,
    ReorderAreasRequest,
)

router = APIRouter(tags=["helpdesk-config-areas"])
logger = logging.getLogger(__name__)


@router.get("")
def list_areas(
    include_inactive: str = "false",
    user: dict = require_perms("helpdesk", ["helpdesk.config.areas.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.area import Area

    query = db.query(Area)
    if include_inactive.lower() != "true":
        query = query.filter_by(is_active=True)

    areas = query.order_by(Area.display_order).all()
    return {"areas": [a.to_dict() for a in areas], "total": len(areas)}


@router.get("/{area_id}")
def get_area(
    area_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.config.areas.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.area import Area

    area = db.get(Area, area_id)
    if not area:
        raise HTTPException(404, detail={"error": "not_found", "message": "Área no encontrada"})

    return {"area": area.to_dict()}


@router.patch("/{area_id}")
def update_area(
    area_id: int,
    body: UpdateAreaRequest,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.areas.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.area import Area
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_areas

    user_id = int(user["sub"])
    area = db.get(Area, area_id)
    if not area:
        raise HTTPException(404, detail={"error": "not_found", "message": "Área no encontrada"})

    before = area.to_dict()

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(area, field, value)

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="area",
        entity_id=area.id,
        action="update",
        before=before,
        after=area.to_dict(),
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(area)
    invalidate_areas()

    logger.info(f"Área {area_id} ({area.code}) actualizada por usuario {user_id}")
    return {"message": "Área actualizada exitosamente", "area": area.to_dict()}


@router.post("/{area_id}/toggle")
def toggle_area(
    area_id: int,
    body: ToggleAreaRequest,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.areas.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.area import Area
    from itcj2.apps.helpdesk.models.ticket import Ticket
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_areas

    user_id = int(user["sub"])
    area = db.get(Area, area_id)
    if not area:
        raise HTTPException(404, detail={"error": "not_found", "message": "Área no encontrada"})

    # Prevenir desactivar un área con tickets activos
    if not body.is_active and area.is_active:
        active_tickets = db.query(Ticket).filter(
            Ticket.area == area.code,
            Ticket.status.notin_(["CLOSED", "CANCELED"]),
        ).count()
        if active_tickets > 0:
            raise HTTPException(400, detail={
                "error": "has_active_tickets",
                "message": (
                    f"No se puede desactivar. Hay {active_tickets} ticket(s) "
                    f"activo(s) en el área '{area.label}'"
                ),
                "active_tickets_count": active_tickets,
            })

    before = area.to_dict()
    area.is_active = body.is_active

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="area",
        entity_id=area.id,
        action="toggle",
        before=before,
        after=area.to_dict(),
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(area)
    invalidate_areas()

    action_label = "activada" if body.is_active else "desactivada"
    logger.info(f"Área {area_id} ({area.code}) {action_label} por usuario {user_id}")
    return {"message": f"Área {action_label} exitosamente", "area": area.to_dict()}


@router.post("/reorder")
def reorder_areas(
    body: ReorderAreasRequest,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.config.areas.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.area import Area
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from itcj2.apps.helpdesk.utils.catalog_cache import invalidate_areas

    user_id = int(user["sub"])

    before_snapshot = []
    for item in body.order:
        if "id" not in item or "display_order" not in item:
            raise HTTPException(400, detail={
                "error": "invalid_order_item",
                "message": "Cada item debe tener id y display_order",
            })
        a = db.get(Area, item["id"])
        if not a:
            raise HTTPException(404, detail={
                "error": "area_not_found",
                "message": f'Área con id {item["id"]} no encontrada',
            })
        before_snapshot.append({"id": a.id, "code": a.code, "display_order": a.display_order})
        a.display_order = item["display_order"]

    after_snapshot = [{"id": item["id"], "display_order": item["display_order"]} for item in body.order]

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="area",
        entity_id=None,
        action="reorder",
        before={"items": before_snapshot},
        after={"items": after_snapshot},
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    invalidate_areas()

    areas = db.query(Area).order_by(Area.display_order).all()
    logger.info(f"Áreas reordenadas por usuario {user_id}")
    return {"message": "Orden actualizado exitosamente", "areas": [a.to_dict() for a in areas]}
