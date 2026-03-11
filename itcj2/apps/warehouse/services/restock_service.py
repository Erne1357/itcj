"""Cálculo del punto de restock automático (rolling 90 días)."""
import logging
import math
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def calculate_restock_point(db: Session, product_id: int) -> None:
    """
    Recalcula el punto de restock automático para un producto.

    Fórmula:
        avg_daily = SUM(quantity consumida en 90 días) / 90
        restock_auto = ceil(avg_daily × (lead_time_days + 3))
        - Mínimo 1 si hay consumo; 0 si no hay consumo en 90 días.

    Actualiza product.restock_point_auto y product.last_restock_calc_at.
    No hace commit — el caller debe hacerlo.
    """
    from itcj2.apps.warehouse.models.product import WarehouseProduct
    from itcj2.apps.warehouse.models.movement import WarehouseMovement

    product = db.get(WarehouseProduct, product_id)
    if not product:
        return

    ninety_days_ago = datetime.now() - timedelta(days=90)

    total_consumed = (
        db.query(func.sum(WarehouseMovement.quantity))
        .filter(
            WarehouseMovement.product_id == product_id,
            WarehouseMovement.movement_type.in_(["CONSUMED", "ADJUSTED_OUT"]),
            WarehouseMovement.performed_at >= ninety_days_ago,
        )
        .scalar()
        or Decimal("0")
    )

    if total_consumed > 0:
        avg_daily = float(total_consumed) / 90.0
        restock_auto = math.ceil(avg_daily * (product.restock_lead_time_days + 3))
        restock_auto = max(1, restock_auto)
    else:
        restock_auto = 0

    product.restock_point_auto = Decimal(str(restock_auto))
    product.last_restock_calc_at = datetime.now()

    logger.debug(
        "Restock recalculado: producto=%s consumido_90d=%s auto=%s",
        product_id, total_consumed, restock_auto,
    )


def recalculate_all(db: Session, department_code: Optional[str] = None) -> int:
    """
    Recalcula el punto de restock para todos los productos activos.
    Útil para tarea programada semanal o ejecución bajo demanda.

    Returns:
        Número de productos procesados.
    """
    from itcj2.apps.warehouse.models.product import WarehouseProduct

    query = db.query(WarehouseProduct).filter(WarehouseProduct.is_active == True)
    if department_code:
        query = query.filter(WarehouseProduct.department_code == department_code)

    products = query.all()
    count = 0

    for product in products:
        try:
            calculate_restock_point(db, product.id)
            count += 1
        except Exception:
            logger.exception("Error calculando restock para producto %s", product.id)

    db.commit()
    logger.info("Recalculo masivo de restock: %s productos procesados (dept=%s)", count, department_code)
    return count
