"""
Warehouse — Consume API (llamado por apps consumidoras)
POST   /consume
GET    /ticket-materials/{source_app}/{source_ticket_id}
DELETE /ticket-materials/{source_app}/{source_ticket_id}/{product_id}
"""
import logging

from fastapi import APIRouter, HTTPException

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.warehouse.schemas.consume import ConsumeRequest

router = APIRouter(tags=["warehouse-consume"])
logger = logging.getLogger(__name__)

_VALID_SOURCE_APPS = frozenset({"helpdesk", "maint"})


@router.post("/consume", status_code=201)
def consume_material(
    body: ConsumeRequest,
    user: dict = require_perms("warehouse", ["warehouse.api.consume"]),
    db: DbSession = None,
):
    """
    Consume stock de un producto para un ticket usando lógica FIFO.
    Llamado internamente desde ticket_service de helpdesk o maint.
    """
    from itcj2.apps.warehouse.services.fifo_service import consume

    user_id = int(user["sub"])
    try:
        movements = consume(
            db=db,
            product_id=body.product_id,
            quantity=body.quantity,
            source_app=body.source_app,
            source_ticket_id=body.source_ticket_id,
            performed_by_id=user_id,
            notes=body.notes,
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(400, detail={"error": "insufficient_stock", "message": str(exc)})

    logger.info(
        "Consumo FIFO: producto=%s qty=%s app=%s ticket=%s por=%s lotes=%s",
        body.product_id, body.quantity, body.source_app,
        body.source_ticket_id, user_id, len(movements),
    )
    return {
        "message": "Material consumido exitosamente",
        "movements_count": len(movements),
        "product_id": body.product_id,
        "quantity_consumed": body.quantity,
    }


@router.get("/ticket-materials/{source_app}/{source_ticket_id}")
def get_ticket_materials(
    source_app: str,
    source_ticket_id: int,
    user: dict = require_perms("warehouse", ["warehouse.api.read"]),
    db: DbSession = None,
):
    """
    Retorna todos los materiales registrados para un ticket específico.
    Usado por helpdesk y maint para mostrar en el detalle del ticket.
    """
    if source_app not in _VALID_SOURCE_APPS:
        raise HTTPException(400, detail={"error": "invalid_source_app", "message": "source_app debe ser 'helpdesk' o 'maint'"})

    from itcj2.apps.warehouse.models.ticket_material import WarehouseTicketMaterial
    from itcj2.apps.warehouse.models.product import WarehouseProduct

    materials = (
        db.query(WarehouseTicketMaterial)
        .filter_by(source_app=source_app, source_ticket_id=source_ticket_id)
        .all()
    )

    result = []
    for m in materials:
        product = db.get(WarehouseProduct, m.product_id)
        result.append({
            "id": m.id,
            "product_id": m.product_id,
            "product_code": product.code if product else None,
            "product_name": product.name if product else None,
            "unit_of_measure": product.unit_of_measure if product else None,
            "quantity_used": m.quantity_used,
            "added_at": m.added_at.isoformat(),
            "notes": m.notes,
        })

    return {
        "source_app": source_app,
        "source_ticket_id": source_ticket_id,
        "materials": result,
        "total": len(result),
    }


@router.delete("/ticket-materials/{source_app}/{source_ticket_id}/{product_id}")
def revert_material(
    source_app: str,
    source_ticket_id: int,
    product_id: int,
    user: dict = require_perms("warehouse", ["warehouse.api.consume"]),
    db: DbSession = None,
):
    """
    Revierte el consumo de un material de un ticket.
    Solo disponible si el ticket no está CLOSED (validar en el caller o service).
    """
    if source_app not in _VALID_SOURCE_APPS:
        raise HTTPException(400, detail={"error": "invalid_source_app", "message": "source_app inválido"})

    from itcj2.apps.warehouse.services.fifo_service import revert_consumption

    user_id = int(user["sub"])
    revert_consumption(
        db=db,
        source_app=source_app,
        source_ticket_id=source_ticket_id,
        product_id=product_id,
        performed_by_id=user_id,
    )
    db.commit()

    logger.info(
        "Reversión de consumo: app=%s ticket=%s producto=%s por=%s",
        source_app, source_ticket_id, product_id, user_id,
    )
    return {"message": "Consumo revertido exitosamente"}
