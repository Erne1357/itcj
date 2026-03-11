"""
Warehouse — Dashboard API
GET /dashboard
GET /low-stock
"""
import logging
from datetime import datetime, date

from fastapi import APIRouter
from sqlalchemy import func

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.warehouse.services.utils import resolve_dept_code

router = APIRouter(tags=["warehouse-dashboard"])
logger = logging.getLogger(__name__)


@router.get("/dashboard")
def get_dashboard(
    dept: str | None = None,
    user: dict = require_perms("warehouse", ["warehouse.page.dashboard"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.models.product import WarehouseProduct
    from itcj2.apps.warehouse.models.category import WarehouseCategory
    from itcj2.apps.warehouse.models.movement import WarehouseMovement
    from itcj2.apps.warehouse.models.stock_entry import WarehouseStockEntry
    from itcj2.apps.warehouse.services.product_service import get_products_below_restock
    from itcj2.apps.warehouse.services.utils import get_stock_totals

    department_code = resolve_dept_code(db, user, dept)

    # Filtro base de productos
    product_q = db.query(WarehouseProduct).filter(WarehouseProduct.is_active == True)
    if department_code:
        product_q = product_q.filter(WarehouseProduct.department_code == department_code)

    total_products = product_q.count()

    # Categorías
    cat_q = db.query(WarehouseCategory).filter(WarehouseCategory.is_active == True)
    if department_code:
        cat_q = cat_q.filter(
            (WarehouseCategory.department_code == department_code)
            | (WarehouseCategory.department_code == None)  # noqa: E711
        )
    total_categories = cat_q.count()

    # Stock total y valor
    all_products = product_q.all()
    product_ids = [p.id for p in all_products]
    stock_map = get_stock_totals(db, product_ids)

    from decimal import Decimal
    total_stock_value = sum(
        stock_map.get(pid, {}).get("total_value", Decimal("0")) for pid in product_ids
    )

    # Productos bajo restock
    low_stock = get_products_below_restock(db, department_code)

    # Movimientos de hoy
    today_start = datetime.combine(date.today(), datetime.min.time())
    mvmt_q = db.query(func.count(WarehouseMovement.id)).filter(
        WarehouseMovement.performed_at >= today_start
    )
    if department_code:
        from itcj2.apps.warehouse.models.movement import WarehouseMovement as WM
        mvmt_q = mvmt_q.join(
            WarehouseProduct, WarehouseProduct.id == WM.product_id
        ).filter(WarehouseProduct.department_code == department_code)
    movements_today = mvmt_q.scalar() or 0

    # Entradas de este mes
    month_start = date.today().replace(day=1)
    entry_q = db.query(func.count(WarehouseStockEntry.id)).filter(
        WarehouseStockEntry.registered_at >= datetime.combine(month_start, datetime.min.time()),
        WarehouseStockEntry.voided == False,
    )
    if department_code:
        entry_q = entry_q.join(
            WarehouseProduct, WarehouseProduct.id == WarehouseStockEntry.product_id
        ).filter(WarehouseProduct.department_code == department_code)
    entries_this_month = entry_q.scalar() or 0

    return {
        "total_products": total_products,
        "total_categories": total_categories,
        "low_stock_count": len(low_stock),
        "total_stock_value": total_stock_value,
        "movements_today": movements_today,
        "entries_this_month": entries_this_month,
        "low_stock_products": [
            {
                "id": p["id"],
                "code": p["code"],
                "name": p["name"],
                "department_code": p["department_code"],
                "total_stock": p["total_stock"],
                "restock_point": p["restock_point"],
                "unit_of_measure": p["unit_of_measure"],
            }
            for p in low_stock
        ],
    }


@router.get("/low-stock")
def get_low_stock(
    dept: str | None = None,
    user: dict = require_perms("warehouse", ["warehouse.page.dashboard"]),
    db: DbSession = None,
):
    """Productos por debajo del punto de restock (para alertas y badge de nav)."""
    from itcj2.apps.warehouse.services.product_service import get_products_below_restock
    from itcj2.apps.warehouse.services.alert_service import get_nav_badge_count

    department_code = resolve_dept_code(db, user, dept)
    low_stock = get_products_below_restock(db, department_code)
    badge_count = get_nav_badge_count(db, department_code)

    return {
        "low_stock_products": low_stock,
        "count": len(low_stock),
        "badge_count": badge_count,
    }
