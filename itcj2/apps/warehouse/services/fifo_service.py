"""
Servicio FIFO del almacén global.

Este es el contrato público para apps consumidoras (helpdesk, maint).
No exponer detalles internos — solo consume(), revert_consumption() y adjust_stock().

Uso desde apps externas:
    from itcj2.apps.warehouse.services.fifo_service import consume, revert_consumption
"""
import logging
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from itcj2.apps.warehouse.models.movement import WarehouseMovement, MOVEMENT_TYPES
from itcj2.apps.warehouse.models.stock_entry import WarehouseStockEntry
from itcj2.apps.warehouse.models.ticket_material import WarehouseTicketMaterial

logger = logging.getLogger(__name__)

_VALID_SOURCE_APPS = frozenset({"helpdesk", "maint"})


def _validate_source_app(source_app: str) -> None:
    if source_app not in _VALID_SOURCE_APPS:
        raise ValueError(f"source_app inválido: '{source_app}'. Debe ser 'helpdesk' o 'maint'.")


def consume(
    db: Session,
    product_id: int,
    quantity: Decimal,
    source_app: str,
    source_ticket_id: int,
    performed_by_id: int,
    notes: Optional[str] = None,
) -> list[WarehouseMovement]:
    """
    Consume stock de un producto usando lógica FIFO.

    Itera los lotes disponibles ordenados por purchase_date ASC,
    desconta la cantidad solicitada distribuyendo entre lotes.

    Hace upsert en WarehouseTicketMaterial para acumular el consumo por ticket.
    Después del consumo dispara check_and_alert y recalcula el restock_point.

    El caller debe hacer db.commit() al finalizar.

    Args:
        db: Sesión de SQLAlchemy.
        product_id: ID del producto a consumir.
        quantity: Cantidad a consumir (> 0).
        source_app: 'helpdesk' o 'maint'.
        source_ticket_id: ID del ticket en la app de origen.
        performed_by_id: ID del usuario que ejecuta el consumo.
        notes: Nota opcional para el movimiento.

    Returns:
        Lista de WarehouseMovement creados.

    Raises:
        ValueError: Si el stock es insuficiente o source_app inválido.
        HTTPException 404: Si el producto no existe.
    """
    _validate_source_app(source_app)

    from itcj2.apps.warehouse.models.product import WarehouseProduct

    product = db.get(WarehouseProduct, product_id)
    if not product or not product.is_active:
        raise HTTPException(
            404, detail={"error": "not_found", "message": f"Producto {product_id} no encontrado o inactivo"}
        )

    # ── Obtener lotes disponibles en orden FIFO ────────────────────────────
    entries = (
        db.query(WarehouseStockEntry)
        .filter(
            WarehouseStockEntry.product_id == product_id,
            WarehouseStockEntry.is_exhausted == False,
            WarehouseStockEntry.voided == False,
            WarehouseStockEntry.quantity_remaining > 0,
        )
        .order_by(WarehouseStockEntry.purchase_date.asc())
        .with_for_update()  # Lock para evitar race conditions en consumo concurrente
        .all()
    )

    total_available = sum(e.quantity_remaining for e in entries)
    if total_available < quantity:
        raise ValueError(
            f"Stock insuficiente para '{product.name}'. "
            f"Disponible: {total_available} {product.unit_of_measure}, "
            f"solicitado: {quantity} {product.unit_of_measure}."
        )

    # ── Consumo FIFO ───────────────────────────────────────────────────────
    movements = []
    remaining = quantity

    for entry in entries:
        if remaining <= 0:
            break

        to_consume = min(entry.quantity_remaining, remaining)
        entry.quantity_remaining -= to_consume
        remaining -= to_consume

        if entry.quantity_remaining == 0:
            entry.is_exhausted = True

        movement = WarehouseMovement(
            product_id=product_id,
            entry_id=entry.id,
            movement_type="CONSUMED",
            quantity=to_consume,
            source_app=source_app,
            source_ticket_id=source_ticket_id,
            performed_by_id=performed_by_id,
            notes=notes,
        )
        db.add(movement)
        movements.append(movement)

    # ── Upsert WarehouseTicketMaterial ─────────────────────────────────────
    existing_tm = (
        db.query(WarehouseTicketMaterial)
        .filter_by(
            source_app=source_app,
            source_ticket_id=source_ticket_id,
            product_id=product_id,
        )
        .first()
    )

    if existing_tm:
        existing_tm.quantity_used += quantity
    else:
        db.add(
            WarehouseTicketMaterial(
                source_app=source_app,
                source_ticket_id=source_ticket_id,
                product_id=product_id,
                quantity_used=quantity,
                added_by_id=performed_by_id,
                notes=notes,
            )
        )

    db.flush()

    # ── Post-consume: alertas y restock ───────────────────────────────────
    try:
        from itcj2.apps.warehouse.services.alert_service import check_and_alert
        from itcj2.apps.warehouse.services.restock_service import calculate_restock_point
        check_and_alert(db, product_id)
        calculate_restock_point(db, product_id)
    except Exception:
        logger.exception("Error en post-consume triggers para producto %s", product_id)
        # No propagar — el consumo ya ocurrió

    logger.info(
        "FIFO consume: producto=%s qty=%s app=%s ticket=%s por=%s",
        product_id, quantity, source_app, source_ticket_id, performed_by_id,
    )
    return movements


def revert_consumption(
    db: Session,
    source_app: str,
    source_ticket_id: int,
    product_id: int,
    performed_by_id: int,
) -> WarehouseTicketMaterial:
    """
    Revierte el consumo de un producto en un ticket.

    Repone el stock al lote más reciente no anulado del producto.
    Elimina el WarehouseTicketMaterial correspondiente.
    Crea un movimiento de tipo RETURNED.

    El caller debe hacer db.commit() al finalizar.

    Raises:
        HTTPException 404: Si no existe el material en el ticket.
    """
    _validate_source_app(source_app)

    ticket_material = (
        db.query(WarehouseTicketMaterial)
        .filter_by(
            source_app=source_app,
            source_ticket_id=source_ticket_id,
            product_id=product_id,
        )
        .first()
    )

    if not ticket_material:
        raise HTTPException(
            404,
            detail={
                "error": "not_found",
                "message": "No se encontró material de ese producto en el ticket",
            },
        )

    quantity_to_return = ticket_material.quantity_used

    # Reponer al lote más reciente no anulado (LIFO para devoluciones)
    latest_entry = (
        db.query(WarehouseStockEntry)
        .filter(
            WarehouseStockEntry.product_id == product_id,
            WarehouseStockEntry.voided == False,
        )
        .order_by(WarehouseStockEntry.purchase_date.desc())
        .first()
    )

    if latest_entry:
        latest_entry.quantity_remaining += quantity_to_return
        if latest_entry.is_exhausted:
            latest_entry.is_exhausted = False

        movement = WarehouseMovement(
            product_id=product_id,
            entry_id=latest_entry.id,
            movement_type="RETURNED",
            quantity=quantity_to_return,
            source_app=source_app,
            source_ticket_id=source_ticket_id,
            performed_by_id=performed_by_id,
            notes=f"Reversión de consumo — ticket {source_app}#{source_ticket_id}",
        )
        db.add(movement)

    db.delete(ticket_material)
    db.flush()

    try:
        from itcj2.apps.warehouse.services.restock_service import calculate_restock_point
        calculate_restock_point(db, product_id)
    except Exception:
        logger.exception("Error en restock recalc tras reversión para producto %s", product_id)

    logger.info(
        "FIFO revert: producto=%s qty=%s app=%s ticket=%s por=%s",
        product_id, quantity_to_return, source_app, source_ticket_id, performed_by_id,
    )
    return ticket_material


def adjust_stock(
    db: Session,
    product_id: int,
    quantity: Decimal,
    adjust_type: str,  # 'IN' | 'OUT'
    notes: str,
    justification: str,
    performed_by_id: int,
) -> WarehouseMovement:
    """
    Ajuste manual de stock (corrección sin folio de compra).

    - ADJUSTED_IN: incrementa el stock (crea un StockEntry si se quiere FIFO)
    - ADJUSTED_OUT: consume usando FIFO igual que un consumo normal
      pero con movement_type=ADJUSTED_OUT y sin source_ticket_id.

    El caller debe hacer db.commit() al finalizar.
    """
    if adjust_type not in ("IN", "OUT"):
        raise ValueError("adjust_type debe ser 'IN' o 'OUT'")

    from itcj2.apps.warehouse.models.product import WarehouseProduct
    from itcj2.apps.warehouse.services.stock_service import get_available_entries

    product = db.get(WarehouseProduct, product_id)
    if not product or not product.is_active:
        raise HTTPException(
            404, detail={"error": "not_found", "message": "Producto no encontrado o inactivo"}
        )

    full_notes = f"{notes} | Justificación: {justification}"

    if adjust_type == "IN":
        # Ajuste positivo: crear entrada de stock con fecha de hoy
        from datetime import date
        from itcj2.apps.warehouse.models.stock_entry import WarehouseStockEntry

        entry = WarehouseStockEntry(
            product_id=product_id,
            quantity_original=quantity,
            quantity_remaining=quantity,
            purchase_date=date.today(),
            purchase_folio="AJUSTE-MANUAL",
            unit_cost=Decimal("0"),  # Ajuste sin costo
            registered_by_id=performed_by_id,
            notes=full_notes,
        )
        db.add(entry)
        db.flush()

        movement = WarehouseMovement(
            product_id=product_id,
            entry_id=entry.id,
            movement_type="ADJUSTED_IN",
            quantity=quantity,
            performed_by_id=performed_by_id,
            notes=full_notes,
        )
        db.add(movement)
        db.flush()

    else:  # OUT — consume FIFO pero con tipo ADJUSTED_OUT
        entries = get_available_entries(db, product_id)
        total_available = sum(e.quantity_remaining for e in entries)

        if total_available < quantity:
            raise ValueError(
                f"Stock insuficiente para ajuste. "
                f"Disponible: {total_available} {product.unit_of_measure}, "
                f"solicitado: {quantity}."
            )

        remaining = quantity
        last_movement = None

        for entry in entries:
            if remaining <= 0:
                break

            to_consume = min(entry.quantity_remaining, remaining)
            entry.quantity_remaining -= to_consume
            remaining -= to_consume

            if entry.quantity_remaining == 0:
                entry.is_exhausted = True

            last_movement = WarehouseMovement(
                product_id=product_id,
                entry_id=entry.id,
                movement_type="ADJUSTED_OUT",
                quantity=to_consume,
                performed_by_id=performed_by_id,
                notes=full_notes,
            )
            db.add(last_movement)

        db.flush()
        movement = last_movement

    try:
        from itcj2.apps.warehouse.services.alert_service import check_and_alert
        from itcj2.apps.warehouse.services.restock_service import calculate_restock_point
        check_and_alert(db, product_id)
        calculate_restock_point(db, product_id)
    except Exception:
        logger.exception("Error en post-adjust triggers para producto %s", product_id)

    logger.info(
        "Ajuste de stock: producto=%s tipo=%s qty=%s por=%s",
        product_id, adjust_type, quantity, performed_by_id,
    )
    return movement
