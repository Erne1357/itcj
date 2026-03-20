"""Utilidades compartidas entre los services del módulo warehouse."""
import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_user_dept_code(db: Session, user_id: int) -> Optional[str]:
    """
    Obtiene el department_code del usuario a través de su puesto activo principal.
    Retorna None si el usuario no tiene puesto asignado con departamento.
    """
    from itcj2.core.models.position import UserPosition, Position
    from itcj2.core.models.department import Department

    row = (
        db.query(Department.code)
        .join(Position, Position.department_id == Department.id)
        .join(UserPosition, UserPosition.position_id == Position.id)
        .filter(
            UserPosition.user_id == user_id,
            UserPosition.is_active == True,
        )
        .first()
    )
    return row[0] if row else None


def resolve_dept_code(db: Session, user: dict, dept_override: Optional[str] = None) -> Optional[str]:
    """
    Resuelve el department_code para filtrar datos del almacén.

    - Superadmin (role=admin): puede pasar ?dept= para ver un dept específico
      o None para ver todos los departamentos.
    - Usuarios regulares: se toma el dept de su puesto activo.
    """
    if user.get("role") == "admin":
        return dept_override  # None = sin filtro de dept (ve todo)

    return get_user_dept_code(db, int(user["sub"]))


def get_stock_totals(db: Session, product_ids: list[int]) -> dict:
    """
    Calcula stock disponible y valor total por producto en una sola query.
    Retorna dict[product_id → {total_stock, total_value}].
    """
    if not product_ids:
        return {}

    from sqlalchemy import func
    from itcj2.apps.warehouse.models.stock_entry import WarehouseStockEntry

    rows = (
        db.query(
            WarehouseStockEntry.product_id,
            func.sum(WarehouseStockEntry.quantity_remaining).label("total_stock"),
            func.sum(
                WarehouseStockEntry.quantity_remaining * WarehouseStockEntry.unit_cost
            ).label("total_value"),
        )
        .filter(
            WarehouseStockEntry.product_id.in_(product_ids),
            WarehouseStockEntry.is_exhausted == False,
            WarehouseStockEntry.voided == False,
        )
        .group_by(WarehouseStockEntry.product_id)
        .all()
    )

    return {
        row.product_id: {
            "total_stock": row.total_stock or Decimal("0"),
            "total_value": row.total_value or Decimal("0"),
        }
        for row in rows
    }


def enrich_product(product, stock_map: dict) -> dict:
    """
    Convierte un WarehouseProduct en dict con campos de stock calculados.
    Usado por product_service para devolver WarehouseProductWithStockOut.
    """
    stock = stock_map.get(product.id, {"total_stock": Decimal("0"), "total_value": Decimal("0")})
    total_stock = stock["total_stock"]
    restock_point = (
        product.restock_point_override
        if product.restock_point_override is not None
        else product.restock_point_auto
    )

    return {
        "id": product.id,
        "code": product.code,
        "name": product.name,
        "description": product.description,
        "category_name": product.subcategory.category.name if product.subcategory and product.subcategory.category else None,
        "subcategory_id": product.subcategory_id,
        "subcategory_name": product.subcategory.name if product.subcategory else None,
        "department_code": product.department_code,
        "unit_of_measure": product.unit_of_measure,
        "icon": product.icon,
        "is_active": product.is_active,
        "restock_point_auto": product.restock_point_auto,
        "restock_point_override": product.restock_point_override,
        "restock_lead_time_days": product.restock_lead_time_days,
        "last_restock_calc_at": product.last_restock_calc_at,
        "created_at": product.created_at,
        "updated_at": product.updated_at,
        "total_stock": total_stock,
        "is_below_restock": total_stock <= restock_point,
        "restock_point": restock_point,
        "total_stock_value": stock["total_value"],
    }
