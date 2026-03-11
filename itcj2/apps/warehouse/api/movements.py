"""
Warehouse — Movements API
GET  /movements
POST /adjust
"""
import logging

from fastapi import APIRouter

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.warehouse.schemas.stock import AdjustRequest
from itcj2.apps.warehouse.services.utils import resolve_dept_code

router = APIRouter(tags=["warehouse-movements"])
logger = logging.getLogger(__name__)


@router.get("/movements")
def list_movements(
    product_id: int | None = None,
    movement_type: str | None = None,
    source_app: str | None = None,
    source_ticket_id: int | None = None,
    page: int = 1,
    per_page: int = 30,
    dept: str | None = None,
    user: dict = require_perms("warehouse", ["warehouse.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.models.movement import WarehouseMovement
    from itcj2.apps.warehouse.models.product import WarehouseProduct
    from itcj2.models.base import paginate

    query = db.query(WarehouseMovement)

    department_code = resolve_dept_code(db, user, dept)
    if department_code:
        query = query.join(
            WarehouseProduct, WarehouseProduct.id == WarehouseMovement.product_id
        ).filter(WarehouseProduct.department_code == department_code)

    if product_id:
        query = query.filter(WarehouseMovement.product_id == product_id)
    if movement_type:
        query = query.filter(WarehouseMovement.movement_type == movement_type.upper())
    if source_app:
        query = query.filter(WarehouseMovement.source_app == source_app)
    if source_ticket_id:
        query = query.filter(WarehouseMovement.source_ticket_id == source_ticket_id)

    query = query.order_by(WarehouseMovement.performed_at.desc())
    result = paginate(query, page=page, per_page=per_page)

    return {
        "movements": [
            {
                "id": m.id,
                "product_id": m.product_id,
                "entry_id": m.entry_id,
                "movement_type": m.movement_type,
                "quantity": m.quantity,
                "source_app": m.source_app,
                "source_ticket_id": m.source_ticket_id,
                "performed_by_id": m.performed_by_id,
                "performed_at": m.performed_at.isoformat(),
                "notes": m.notes,
            }
            for m in result.items
        ],
        "total": result.total,
        "page": result.page,
        "pages": result.pages,
    }


@router.post("/adjust")
def adjust_stock(
    body: AdjustRequest,
    user: dict = require_perms("warehouse", ["warehouse.api.adjust"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.fifo_service import adjust_stock as svc_adjust

    user_id = int(user["sub"])
    try:
        movement = svc_adjust(
            db=db,
            product_id=body.product_id,
            quantity=body.quantity,
            adjust_type=body.adjust_type,
            notes=body.notes,
            justification=body.justification,
            performed_by_id=user_id,
        )
        db.commit()
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(400, detail={"error": "insufficient_stock", "message": str(exc)})

    logger.info(
        "Ajuste de stock: producto=%s tipo=%s qty=%s por usuario=%s",
        body.product_id, body.adjust_type, body.quantity, user_id,
    )
    return {
        "message": f"Ajuste de stock ({body.adjust_type}) registrado exitosamente",
        "movement_id": movement.id if movement else None,
    }
