"""Gestión de entradas de stock (lotes FIFO)."""
import logging
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from itcj2.apps.warehouse.models.movement import WarehouseMovement
from itcj2.apps.warehouse.models.stock_entry import WarehouseStockEntry
from itcj2.models.base import paginate

logger = logging.getLogger(__name__)


def get_available_entries(db: Session, product_id: int) -> list[WarehouseStockEntry]:
    """Retorna lotes disponibles ordenados por purchase_date ASC (orden FIFO)."""
    return (
        db.query(WarehouseStockEntry)
        .filter(
            WarehouseStockEntry.product_id == product_id,
            WarehouseStockEntry.is_exhausted == False,
            WarehouseStockEntry.voided == False,
            WarehouseStockEntry.quantity_remaining > 0,
        )
        .order_by(WarehouseStockEntry.purchase_date.asc())
        .all()
    )


def list_entries(
    db: Session,
    product_id: Optional[int] = None,
    department_code: Optional[str] = None,
    include_voided: bool = False,
    page: int = 1,
    per_page: int = 20,
):
    """Lista entradas de stock con paginación y filtros."""
    from itcj2.apps.warehouse.models.product import WarehouseProduct

    query = db.query(WarehouseStockEntry)

    if product_id:
        query = query.filter(WarehouseStockEntry.product_id == product_id)

    if department_code:
        query = (
            query.join(WarehouseProduct, WarehouseProduct.id == WarehouseStockEntry.product_id)
            .filter(WarehouseProduct.department_code == department_code)
        )

    if not include_voided:
        query = query.filter(WarehouseStockEntry.voided == False)

    query = query.order_by(WarehouseStockEntry.registered_at.desc())
    return paginate(query, page=page, per_page=per_page)


def get_entry(db: Session, entry_id: int) -> WarehouseStockEntry:
    entry = db.get(WarehouseStockEntry, entry_id)
    if not entry:
        raise HTTPException(404, detail={"error": "not_found", "message": "Entrada de stock no encontrada"})
    return entry


def register_entry(db: Session, data, registered_by_id: int) -> WarehouseStockEntry:
    """
    Registra una nueva entrada de stock (compra/lote).
    Crea automáticamente un movimiento de tipo ENTRY.
    """
    from itcj2.apps.warehouse.models.product import WarehouseProduct

    product = db.get(WarehouseProduct, data.product_id)
    if not product or not product.is_active:
        raise HTTPException(
            404, detail={"error": "not_found", "message": "Producto no encontrado o inactivo"}
        )

    entry = WarehouseStockEntry(
        product_id=data.product_id,
        quantity_original=data.quantity,
        quantity_remaining=data.quantity,
        purchase_date=data.purchase_date,
        purchase_folio=data.purchase_folio.strip(),
        unit_cost=data.unit_cost,
        supplier=data.supplier.strip() if data.supplier else None,
        registered_by_id=registered_by_id,
        notes=data.notes,
        is_exhausted=False,
        voided=False,
    )
    db.add(entry)
    db.flush()  # Obtener entry.id antes de crear el movimiento

    movement = WarehouseMovement(
        product_id=data.product_id,
        entry_id=entry.id,
        movement_type="ENTRY",
        quantity=data.quantity,
        performed_by_id=registered_by_id,
        notes=f"Entrada — Folio: {data.purchase_folio}",
    )
    db.add(movement)
    db.flush()

    logger.info(
        "Entrada de stock registrada: producto=%s cantidad=%s folio=%s por usuario=%s",
        data.product_id, data.quantity, data.purchase_folio, registered_by_id,
    )
    return entry


def void_entry(
    db: Session, entry_id: int, reason: str, voided_by_id: int
) -> WarehouseStockEntry:
    """
    Anula un lote de stock.
    Solo se puede anular si no ha sido completamente consumido.
    """
    entry = get_entry(db, entry_id)

    if entry.voided:
        raise HTTPException(
            400, detail={"error": "already_voided", "message": "Esta entrada ya fue anulada"}
        )

    if entry.quantity_remaining < entry.quantity_original:
        raise HTTPException(
            400,
            detail={
                "error": "partially_consumed",
                "message": (
                    f"No se puede anular: se han consumido "
                    f"{entry.quantity_original - entry.quantity_remaining} unidades de este lote"
                ),
            },
        )

    entry.voided = True
    entry.voided_by_id = voided_by_id
    entry.voided_at = datetime.now()
    entry.void_reason = reason.strip()

    movement = WarehouseMovement(
        product_id=entry.product_id,
        entry_id=entry.id,
        movement_type="VOIDED",
        quantity=entry.quantity_remaining,
        performed_by_id=voided_by_id,
        notes=f"Anulación de lote — Razón: {reason.strip()}",
    )
    db.add(movement)
    db.flush()

    logger.info("Entrada %s anulada por usuario %s", entry_id, voided_by_id)
    return entry
