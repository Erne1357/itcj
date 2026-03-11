"""
Warehouse — Products API
GET    /products
POST   /products
GET    /products/available          (autocomplete para tickets)
GET    /products/{id}
PATCH  /products/{id}
DELETE /products/{id}
POST   /products/{id}/recalculate-restock
PUT    /products/{id}/restock-override
"""
import logging

from fastapi import APIRouter

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.warehouse.schemas.products import (
    WarehouseProductCreate,
    WarehouseProductUpdate,
    RestockOverrideRequest,
)
from itcj2.apps.warehouse.services.utils import resolve_dept_code

router = APIRouter(tags=["warehouse-products"])
logger = logging.getLogger(__name__)


@router.get("/products")
def list_products(
    include_inactive: bool = False,
    search: str | None = None,
    subcategory_id: int | None = None,
    dept: str | None = None,
    user: dict = require_perms("warehouse", ["warehouse.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.product_service import list_products as svc_list

    department_code = resolve_dept_code(db, user, dept)
    products = svc_list(db, department_code, include_inactive, search, subcategory_id)
    return {"products": products, "total": len(products)}


@router.get("/products/available")
def get_available_products(
    search: str | None = None,
    limit: int = 20,
    dept: str | None = None,
    user: dict = require_perms("warehouse", ["warehouse.api.read"]),
    db: DbSession = None,
):
    """Autocomplete para el campo de materiales en tickets."""
    from itcj2.apps.warehouse.services.product_service import get_available_for_autocomplete

    department_code = resolve_dept_code(db, user, dept)
    products = get_available_for_autocomplete(db, department_code, search, min(limit, 50))
    return {"products": products, "total": len(products)}


@router.get("/products/{product_id}")
def get_product(
    product_id: int,
    user: dict = require_perms("warehouse", ["warehouse.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.product_service import get_product_with_stock
    from itcj2.apps.warehouse.services.stock_service import get_available_entries

    product = get_product_with_stock(db, product_id)

    # Incluir lotes disponibles en el detalle
    entries = get_available_entries(db, product_id)
    product["available_entries"] = [
        {
            "id": e.id,
            "quantity_remaining": e.quantity_remaining,
            "purchase_date": e.purchase_date.isoformat(),
            "purchase_folio": e.purchase_folio,
            "unit_cost": e.unit_cost,
            "supplier": e.supplier,
        }
        for e in entries
    ]
    return {"product": product}


@router.post("/products", status_code=201)
def create_product(
    body: WarehouseProductCreate,
    user: dict = require_perms("warehouse", ["warehouse.api.products.create"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.product_service import create_product as svc_create

    user_id = int(user["sub"])
    product = svc_create(db, body, user_id)
    db.commit()

    logger.info("Producto %s creado por usuario %s", product.code, user_id)
    return {
        "message": "Producto creado exitosamente",
        "product": {"id": product.id, "code": product.code, "name": product.name},
    }


@router.patch("/products/{product_id}")
def update_product(
    product_id: int,
    body: WarehouseProductUpdate,
    user: dict = require_perms("warehouse", ["warehouse.api.products.update"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.product_service import update_product as svc_update

    product = svc_update(db, product_id, body)
    db.commit()
    return {"message": "Producto actualizado", "product": {"id": product.id, "name": product.name}}


@router.delete("/products/{product_id}")
def deactivate_product(
    product_id: int,
    user: dict = require_perms("warehouse", ["warehouse.api.products.delete"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.product_service import deactivate_product as svc_deactivate

    svc_deactivate(db, product_id)
    db.commit()
    return {"message": "Producto desactivado exitosamente"}


@router.post("/products/{product_id}/recalculate-restock")
def recalculate_restock(
    product_id: int,
    user: dict = require_perms("warehouse", ["warehouse.api.products.update"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.restock_service import calculate_restock_point
    from itcj2.apps.warehouse.services.product_service import get_product_with_stock

    calculate_restock_point(db, product_id)
    db.commit()
    product = get_product_with_stock(db, product_id)
    return {
        "message": "Punto de restock recalculado",
        "restock_point_auto": product["restock_point_auto"],
        "restock_point": product["restock_point"],
    }


@router.put("/products/{product_id}/restock-override")
def set_restock_override(
    product_id: int,
    body: RestockOverrideRequest,
    user: dict = require_perms("warehouse", ["warehouse.api.products.update"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.product_service import set_restock_override as svc_override

    product = svc_override(db, product_id, body.restock_point_override)
    db.commit()

    action = "establecido" if body.restock_point_override is not None else "removido"
    return {
        "message": f"Override de restock {action}",
        "restock_point_override": product.restock_point_override,
    }
