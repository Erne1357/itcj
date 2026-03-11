"""CRUD y consultas de productos del almacén global."""
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from itcj2.apps.warehouse.models.product import WarehouseProduct
from itcj2.apps.warehouse.models.stock_entry import WarehouseStockEntry
from itcj2.apps.warehouse.services.utils import enrich_product, get_stock_totals

logger = logging.getLogger(__name__)


def _next_product_code(db: Session) -> str:
    """Genera el siguiente código WAR-XXX, garantizando unicidad."""
    count = db.query(func.count(WarehouseProduct.id)).scalar() or 0
    candidate = f"WAR-{count + 1:03d}"

    # Asegurar unicidad por si hay saltos en IDs
    while db.query(WarehouseProduct).filter_by(code=candidate).first():
        count += 1
        candidate = f"WAR-{count + 1:03d}"

    return candidate


# ── Consultas ─────────────────────────────────────────────────────────────────

def list_products(
    db: Session,
    department_code: Optional[str],
    include_inactive: bool = False,
    search: Optional[str] = None,
    subcategory_id: Optional[int] = None,
) -> list[dict]:
    """Lista productos enriquecidos con datos de stock calculados en SQL."""
    query = db.query(WarehouseProduct)

    if department_code is not None:
        query = query.filter(WarehouseProduct.department_code == department_code)

    if not include_inactive:
        query = query.filter(WarehouseProduct.is_active == True)

    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            WarehouseProduct.name.ilike(term) | WarehouseProduct.code.ilike(term)
        )

    if subcategory_id:
        query = query.filter(WarehouseProduct.subcategory_id == subcategory_id)

    products = query.order_by(WarehouseProduct.name).all()
    stock_map = get_stock_totals(db, [p.id for p in products])

    return [enrich_product(p, stock_map) for p in products]


def get_product(db: Session, product_id: int) -> WarehouseProduct:
    product = db.get(WarehouseProduct, product_id)
    if not product:
        raise HTTPException(404, detail={"error": "not_found", "message": "Producto no encontrado"})
    return product


def get_product_with_stock(db: Session, product_id: int) -> dict:
    product = get_product(db, product_id)
    stock_map = get_stock_totals(db, [product_id])
    return enrich_product(product, stock_map)


def get_available_for_autocomplete(
    db: Session,
    department_code: Optional[str],
    search: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """
    Retorna productos con stock > 0 para el autocomplete en tickets.
    Filtrado por dept automáticamente.
    """
    query = db.query(WarehouseProduct).filter(WarehouseProduct.is_active == True)

    if department_code is not None:
        query = query.filter(WarehouseProduct.department_code == department_code)

    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            WarehouseProduct.name.ilike(term) | WarehouseProduct.code.ilike(term)
        )

    products = query.order_by(WarehouseProduct.name).limit(limit * 3).all()  # 3x para filtrar con stock
    stock_map = get_stock_totals(db, [p.id for p in products])

    result = []
    for p in products:
        stock_info = stock_map.get(p.id, {"total_stock": Decimal("0"), "total_value": Decimal("0")})
        total_stock = stock_info["total_stock"]
        if total_stock > 0:
            result.append({
                "id": p.id,
                "code": p.code,
                "name": p.name,
                "unit_of_measure": p.unit_of_measure,
                "total_stock": total_stock,
                "department_code": p.department_code,
            })
        if len(result) >= limit:
            break

    return result


def get_products_below_restock(
    db: Session, department_code: Optional[str]
) -> list[dict]:
    """Productos cuyo stock está por debajo del punto de restock."""
    all_products = list_products(db, department_code, include_inactive=False)
    return [p for p in all_products if p["is_below_restock"]]


# ── Mutaciones ────────────────────────────────────────────────────────────────

def create_product(db: Session, data, created_by_id: int) -> WarehouseProduct:
    from itcj2.apps.warehouse.models.subcategory import WarehouseSubcategory

    sub = db.get(WarehouseSubcategory, data.subcategory_id)
    if not sub or not sub.is_active:
        raise HTTPException(
            400, detail={"error": "invalid_subcategory", "message": "Subcategoría no válida o inactiva"}
        )

    code = _next_product_code(db)
    product = WarehouseProduct(
        code=code,
        name=data.name.strip(),
        description=data.description.strip() if data.description else None,
        subcategory_id=data.subcategory_id,
        department_code=data.department_code,
        unit_of_measure=data.unit_of_measure.strip(),
        icon=data.icon,
        is_active=True,
        restock_lead_time_days=data.restock_lead_time_days,
        created_by_id=created_by_id,
    )
    db.add(product)
    db.flush()
    logger.info("Producto '%s' (%s) creado por usuario %s", product.name, product.code, created_by_id)
    return product


def update_product(db: Session, product_id: int, data) -> WarehouseProduct:
    product = get_product(db, product_id)

    if data.name is not None:
        product.name = data.name.strip()
    if data.description is not None:
        product.description = data.description.strip() if data.description else None
    if data.subcategory_id is not None:
        from itcj2.apps.warehouse.models.subcategory import WarehouseSubcategory
        sub = db.get(WarehouseSubcategory, data.subcategory_id)
        if not sub or not sub.is_active:
            raise HTTPException(
                400, detail={"error": "invalid_subcategory", "message": "Subcategoría no válida"}
            )
        product.subcategory_id = data.subcategory_id
    if data.unit_of_measure is not None:
        product.unit_of_measure = data.unit_of_measure.strip()
    if data.icon is not None:
        product.icon = data.icon
    if data.restock_lead_time_days is not None:
        product.restock_lead_time_days = data.restock_lead_time_days

    product.updated_at = datetime.now()
    db.flush()
    return product


def deactivate_product(db: Session, product_id: int) -> WarehouseProduct:
    product = get_product(db, product_id)
    product.is_active = False
    product.updated_at = datetime.now()
    db.flush()
    logger.info("Producto %s (%s) desactivado", product.code, product.name)
    return product


def set_restock_override(
    db: Session, product_id: int, override_value: Optional[Decimal]
) -> WarehouseProduct:
    product = get_product(db, product_id)
    product.restock_point_override = override_value
    product.updated_at = datetime.now()
    db.flush()
    return product
