"""
Warehouse — Reports API
GET /reports/movements
GET /reports/consumption
GET /reports/stock-valuation
"""
import logging
from datetime import datetime, date, timedelta
from decimal import Decimal

from fastapi import APIRouter
from sqlalchemy import func

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.warehouse.services.utils import resolve_dept_code

router = APIRouter(tags=["warehouse-reports"])
logger = logging.getLogger(__name__)


def _parse_date(value: str | None, default: date) -> date:
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        return default


@router.get("/reports/movements")
def report_movements(
    date_from: str | None = None,
    date_to: str | None = None,
    movement_type: str | None = None,
    product_id: int | None = None,
    dept: str | None = None,
    user: dict = require_perms("warehouse", ["warehouse.api.reports.read"]),
    db: DbSession = None,
):
    """Reporte de movimientos por período."""
    from itcj2.apps.warehouse.models.movement import WarehouseMovement
    from itcj2.apps.warehouse.models.product import WarehouseProduct

    department_code = resolve_dept_code(db, user, dept)
    today = date.today()
    d_from = _parse_date(date_from, today - timedelta(days=30))
    d_to = _parse_date(date_to, today)

    query = db.query(WarehouseMovement).filter(
        WarehouseMovement.performed_at >= datetime.combine(d_from, datetime.min.time()),
        WarehouseMovement.performed_at <= datetime.combine(d_to, datetime.max.time()),
    )

    if department_code:
        query = query.join(
            WarehouseProduct, WarehouseProduct.id == WarehouseMovement.product_id
        ).filter(WarehouseProduct.department_code == department_code)

    if product_id:
        query = query.filter(WarehouseMovement.product_id == product_id)
    if movement_type:
        query = query.filter(WarehouseMovement.movement_type == movement_type.upper())

    movements = query.order_by(WarehouseMovement.performed_at.desc()).limit(500).all()

    # Agrupar por tipo
    summary: dict[str, dict] = {}
    for m in movements:
        mt = m.movement_type
        if mt not in summary:
            summary[mt] = {"count": 0, "total_quantity": Decimal("0")}
        summary[mt]["count"] += 1
        summary[mt]["total_quantity"] += m.quantity

    return {
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),
        "total_movements": len(movements),
        "summary_by_type": summary,
        "movements": [
            {
                "id": m.id,
                "product_id": m.product_id,
                "movement_type": m.movement_type,
                "quantity": m.quantity,
                "source_app": m.source_app,
                "source_ticket_id": m.source_ticket_id,
                "performed_at": m.performed_at.isoformat(),
                "notes": m.notes,
            }
            for m in movements
        ],
    }


@router.get("/reports/consumption")
def report_consumption(
    date_from: str | None = None,
    date_to: str | None = None,
    dept: str | None = None,
    user: dict = require_perms("warehouse", ["warehouse.api.reports.read"]),
    db: DbSession = None,
):
    """Consumo por producto y categoría en el período."""
    from itcj2.apps.warehouse.models.movement import WarehouseMovement
    from itcj2.apps.warehouse.models.product import WarehouseProduct
    from itcj2.apps.warehouse.models.subcategory import WarehouseSubcategory
    from itcj2.apps.warehouse.models.category import WarehouseCategory

    department_code = resolve_dept_code(db, user, dept)
    today = date.today()
    d_from = _parse_date(date_from, today - timedelta(days=30))
    d_to = _parse_date(date_to, today)

    rows = (
        db.query(
            WarehouseProduct.id.label("product_id"),
            WarehouseProduct.code,
            WarehouseProduct.name,
            WarehouseProduct.unit_of_measure,
            WarehouseCategory.name.label("category_name"),
            func.sum(WarehouseMovement.quantity).label("total_consumed"),
            func.count(WarehouseMovement.id).label("movement_count"),
        )
        .join(WarehouseMovement, WarehouseMovement.product_id == WarehouseProduct.id)
        .join(WarehouseSubcategory, WarehouseSubcategory.id == WarehouseProduct.subcategory_id)
        .join(WarehouseCategory, WarehouseCategory.id == WarehouseSubcategory.category_id)
        .filter(
            WarehouseMovement.movement_type.in_(["CONSUMED", "ADJUSTED_OUT"]),
            WarehouseMovement.performed_at >= datetime.combine(d_from, datetime.min.time()),
            WarehouseMovement.performed_at <= datetime.combine(d_to, datetime.max.time()),
        )
    )

    if department_code:
        rows = rows.filter(WarehouseProduct.department_code == department_code)

    rows = rows.group_by(
        WarehouseProduct.id, WarehouseProduct.code, WarehouseProduct.name,
        WarehouseProduct.unit_of_measure, WarehouseCategory.name,
    ).order_by(func.sum(WarehouseMovement.quantity).desc()).all()

    return {
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),
        "products": [
            {
                "product_id": r.product_id,
                "code": r.code,
                "name": r.name,
                "unit_of_measure": r.unit_of_measure,
                "category_name": r.category_name,
                "total_consumed": r.total_consumed,
                "movement_count": r.movement_count,
            }
            for r in rows
        ],
        "total_products_with_consumption": len(rows),
    }


@router.get("/reports/stock-valuation")
def report_stock_valuation(
    dept: str | None = None,
    user: dict = require_perms("warehouse", ["warehouse.api.reports.read"]),
    db: DbSession = None,
):
    """Valoración del inventario actual (FIFO — costo de los lotes disponibles)."""
    from itcj2.apps.warehouse.models.product import WarehouseProduct
    from itcj2.apps.warehouse.models.stock_entry import WarehouseStockEntry
    from itcj2.apps.warehouse.models.category import WarehouseCategory
    from itcj2.apps.warehouse.models.subcategory import WarehouseSubcategory

    department_code = resolve_dept_code(db, user, dept)

    rows = (
        db.query(
            WarehouseProduct.id.label("product_id"),
            WarehouseProduct.code,
            WarehouseProduct.name,
            WarehouseProduct.unit_of_measure,
            WarehouseProduct.department_code,
            WarehouseCategory.name.label("category_name"),
            func.sum(WarehouseStockEntry.quantity_remaining).label("total_stock"),
            func.sum(
                WarehouseStockEntry.quantity_remaining * WarehouseStockEntry.unit_cost
            ).label("total_value"),
        )
        .join(WarehouseStockEntry, WarehouseStockEntry.product_id == WarehouseProduct.id)
        .join(WarehouseSubcategory, WarehouseSubcategory.id == WarehouseProduct.subcategory_id)
        .join(WarehouseCategory, WarehouseCategory.id == WarehouseSubcategory.category_id)
        .filter(
            WarehouseStockEntry.is_exhausted == False,
            WarehouseStockEntry.voided == False,
            WarehouseProduct.is_active == True,
        )
    )

    if department_code:
        rows = rows.filter(WarehouseProduct.department_code == department_code)

    rows = rows.group_by(
        WarehouseProduct.id, WarehouseProduct.code, WarehouseProduct.name,
        WarehouseProduct.unit_of_measure, WarehouseProduct.department_code,
        WarehouseCategory.name,
    ).order_by(func.sum(WarehouseStockEntry.quantity_remaining * WarehouseStockEntry.unit_cost).desc()).all()

    grand_total = sum((r.total_value or Decimal("0")) for r in rows)

    return {
        "generated_at": datetime.now().isoformat(),
        "department_code": department_code,
        "grand_total_value": grand_total,
        "products": [
            {
                "product_id": r.product_id,
                "code": r.code,
                "name": r.name,
                "unit_of_measure": r.unit_of_measure,
                "department_code": r.department_code,
                "category_name": r.category_name,
                "total_stock": r.total_stock or Decimal("0"),
                "total_value": r.total_value or Decimal("0"),
            }
            for r in rows
        ],
        "total_products": len(rows),
    }
