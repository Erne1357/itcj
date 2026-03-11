"""Alertas de restock y badge de navegación del almacén."""
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from itcj2.apps.warehouse.services.utils import get_stock_totals

logger = logging.getLogger(__name__)


def check_and_alert(db: Session, product_id: int) -> bool:
    """
    Verifica si el producto está bajo el punto de restock y, de ser así,
    crea notificaciones para los usuarios del departamento y actualiza
    restock_alert_sent_at para evitar spam (throttle de 24 horas).

    Returns:
        True si se envió alerta, False si no fue necesario.
    """
    from itcj2.apps.warehouse.models.product import WarehouseProduct

    product = db.get(WarehouseProduct, product_id)
    if not product or not product.is_active:
        return False

    stock_map = get_stock_totals(db, [product_id])
    stock_info = stock_map.get(product_id, {"total_stock": Decimal("0"), "total_value": Decimal("0")})
    total_stock = stock_info["total_stock"]

    restock_point = (
        product.restock_point_override
        if product.restock_point_override is not None
        else product.restock_point_auto
    )

    # ¿Está bajo el punto de restock?
    if total_stock > restock_point:
        return False

    # Throttle: solo alertar si nunca se alertó o hace más de 24 horas
    if product.restock_alert_sent_at:
        elapsed = datetime.now() - product.restock_alert_sent_at
        if elapsed < timedelta(hours=24):
            return False

    # Notificar a admins del departamento
    admin_ids = _get_warehouse_admins_for_dept(db, product.department_code)

    for user_id in admin_ids:
        try:
            from itcj2.core.services.notification_service import NotificationService
            NotificationService.create(
                db=db,
                user_id=user_id,
                app_name="warehouse",
                type="LOW_STOCK",
                title=f"Stock bajo: {product.name}",
                body=(
                    f"El producto '{product.name}' ({product.code}) tiene "
                    f"{total_stock} {product.unit_of_measure} disponibles "
                    f"(punto de restock: {restock_point})."
                ),
                data={
                    "product_id": product.id,
                    "product_code": product.code,
                    "total_stock": str(total_stock),
                    "restock_point": str(restock_point),
                    "department_code": product.department_code,
                },
            )
        except Exception:
            logger.exception("Error creando notificación para usuario %s", user_id)

    product.restock_alert_sent_at = datetime.now()
    logger.info(
        "Alerta de stock bajo enviada: producto=%s stock=%s punto=%s dept=%s admins=%s",
        product.code, total_stock, restock_point, product.department_code, len(admin_ids),
    )
    return True


def get_nav_badge_count(db: Session, department_code: Optional[str]) -> int:
    """
    Cuenta de productos bajo el punto de restock para mostrar en el badge de navegación.
    Query eficiente que evita cargar todos los productos.
    """
    from itcj2.apps.warehouse.models.product import WarehouseProduct
    from itcj2.apps.warehouse.models.stock_entry import WarehouseStockEntry

    # Stock disponible por producto (solo activos y no anulados)
    stock_subq = (
        db.query(
            WarehouseStockEntry.product_id,
            func.sum(WarehouseStockEntry.quantity_remaining).label("total_stock"),
        )
        .filter(
            WarehouseStockEntry.is_exhausted == False,
            WarehouseStockEntry.voided == False,
        )
        .group_by(WarehouseStockEntry.product_id)
        .subquery()
    )

    query = db.query(WarehouseProduct).outerjoin(
        stock_subq, stock_subq.c.product_id == WarehouseProduct.id
    ).filter(WarehouseProduct.is_active == True)

    if department_code:
        query = query.filter(WarehouseProduct.department_code == department_code)

    products = query.all()

    count = 0
    for p in products:
        restock_point = (
            p.restock_point_override
            if p.restock_point_override is not None
            else p.restock_point_auto
        )
        # Para el badge solo nos importa si está bajo restock
        stock_map = get_stock_totals(db, [p.id])
        total_stock = stock_map.get(p.id, {}).get("total_stock", Decimal("0"))
        if total_stock <= restock_point:
            count += 1

    return count


def _get_warehouse_admins_for_dept(db: Session, department_code: str) -> list[int]:
    """
    Obtiene los IDs de usuarios con acceso de administración al almacén
    en el departamento especificado (vía puestos activos).
    """
    from itcj2.core.models.position import UserPosition, Position
    from itcj2.core.models.department import Department

    dept = db.query(Department).filter_by(code=department_code).first()
    if not dept:
        return []

    rows = (
        db.query(UserPosition.user_id)
        .join(Position, Position.id == UserPosition.position_id)
        .filter(
            Position.department_id == dept.id,
            UserPosition.is_active == True,
        )
        .distinct()
        .all()
    )
    return [r[0] for r in rows]
