"""
Maint → Warehouse proxy API.
Todas las operaciones se limitan a department_code = 'equipment_maint'.

Rutas montadas en /api/maint/v2/warehouse/...
"""
import logging
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from itcj2.dependencies import DbSession, require_perms

logger = logging.getLogger(__name__)

router = APIRouter(tags=["maint-warehouse"])

_DEPT = "equipment_maint"
_PERM = "maint.admin.warehouse.manage"


def _assert_category_owned(db, cat_id: int):
    """Lanza 404 si la categoría no existe o no pertenece a equipment_maint."""
    from itcj2.apps.warehouse.models.category import WarehouseCategory
    cat = db.query(WarehouseCategory).filter(
        WarehouseCategory.id == cat_id,
        WarehouseCategory.department_code == _DEPT,
    ).first()
    if not cat:
        raise HTTPException(404, detail={"error": "not_found", "message": "Categoría no encontrada"})


# ── Schemas locales ────────────────────────────────────────────────────────

class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = None

class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = None

class SubcategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = None

class SubcategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = None

class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    unit_of_measure: str = Field(min_length=1, max_length=30)
    subcategory_id: int
    description: Optional[str] = None
    lead_time_days: int = 7

class ProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    unit_of_measure: Optional[str] = Field(default=None, min_length=1, max_length=30)
    subcategory_id: Optional[int] = None
    description: Optional[str] = None
    lead_time_days: Optional[int] = None

class StockEntryCreate(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0)
    purchase_folio: Optional[str] = None
    supplier: Optional[str] = None
    purchase_date: str  # YYYY-MM-DD
    notes: Optional[str] = None

class VoidRequest(BaseModel):
    reason: str = Field(min_length=1)


# ── Dashboard ──────────────────────────────────────────────────────────────

@router.get("/dashboard")
def get_dashboard(
    user: dict = require_perms("maint", [_PERM]),
    db: DbSession = None,
):
    from datetime import date, datetime
    from sqlalchemy import func
    from itcj2.apps.warehouse.models.product import WarehouseProduct
    from itcj2.apps.warehouse.models.movement import WarehouseMovement
    from itcj2.apps.warehouse.models.stock_entry import WarehouseStockEntry
    from itcj2.apps.warehouse.services.product_service import get_products_below_restock
    from itcj2.apps.warehouse.services.utils import get_stock_totals

    total_products = db.query(func.count(WarehouseProduct.id)).filter(
        WarehouseProduct.department_code == _DEPT,
        WarehouseProduct.is_active == True,
    ).scalar() or 0

    product_ids = [
        r[0] for r in db.query(WarehouseProduct.id).filter(
            WarehouseProduct.department_code == _DEPT,
            WarehouseProduct.is_active == True,
        ).all()
    ]

    stock_map = get_stock_totals(db, product_ids) if product_ids else {}
    total_value = sum(v["total_value"] for v in stock_map.values())

    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    movements_today = (
        db.query(func.count(WarehouseMovement.id)).filter(
            WarehouseMovement.product_id.in_(product_ids),
            WarehouseMovement.performed_at.between(today_start, today_end),
        ).scalar() or 0
    ) if product_ids else 0

    month_start = today.replace(day=1)
    entries_month = (
        db.query(func.count(WarehouseStockEntry.id)).filter(
            WarehouseStockEntry.product_id.in_(product_ids),
            WarehouseStockEntry.purchase_date >= month_start,
            WarehouseStockEntry.voided == False,
        ).scalar() or 0
    ) if product_ids else 0

    # get_products_below_restock returns list[dict] (already enriched)
    low_stock_products = get_products_below_restock(db, _DEPT)
    low_stock_count = len(low_stock_products)

    low_stock_list = [
        {
            "id": p["id"],
            "code": p["code"],
            "name": p["name"],
            "unit_of_measure": p["unit_of_measure"],
            "total_stock": float(p["total_stock"]),
            "restock_point": float(p["restock_point"] or 0),
        }
        for p in low_stock_products[:20]
    ]

    return {
        "total_products": total_products,
        "low_stock_count": low_stock_count,
        "total_stock_value": float(total_value),
        "movements_today": movements_today,
        "entries_this_month": entries_month,
        "low_stock_products": low_stock_list,
    }


# ── Categories ─────────────────────────────────────────────────────────────

@router.get("/categories")
def list_categories(
    with_subcategories: bool = True,
    user: dict = require_perms("maint", [_PERM]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.models.category import WarehouseCategory

    # Filtro estricto: solo categorías propias de equipment_maint (no globales NULL)
    query = db.query(WarehouseCategory).filter(
        WarehouseCategory.department_code == _DEPT,
        WarehouseCategory.is_active == True,
    ).order_by(WarehouseCategory.display_order, WarehouseCategory.name)
    cats = query.all()

    def _cat_dict(c):
        d = {"id": c.id, "name": c.name, "description": c.description, "is_active": c.is_active}
        if with_subcategories:
            d["subcategories"] = [
                {"id": s.id, "name": s.name, "description": s.description, "is_active": s.is_active}
                for s in (c.subcategories or []) if s.is_active
            ]
        return d

    return {"categories": [_cat_dict(c) for c in cats]}


@router.post("/categories", status_code=201)
def create_category(
    body: CategoryCreate,
    user: dict = require_perms("maint", [_PERM]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.category_service import create_category as svc

    # The service expects a data object with .name, .description, .icon,
    # .department_code, .display_order attributes
    data = SimpleNamespace(
        name=body.name,
        description=body.description,
        icon="bi-folder",
        department_code=_DEPT,
        display_order=0,
    )
    cat = svc(db, data, _DEPT)
    return {"id": cat.id, "name": cat.name}


@router.patch("/categories/{cat_id}")
def update_category(
    cat_id: int,
    body: CategoryUpdate,
    user: dict = require_perms("maint", [_PERM]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.category_service import update_category as svc

    _assert_category_owned(db, cat_id)
    data = SimpleNamespace(
        name=body.name,
        description=body.description,
        icon=None,
        display_order=None,
    )
    cat = svc(db, cat_id, data)
    return {"id": cat.id, "name": cat.name}


@router.get("/categories/{cat_id}/subcategories")
def list_subcategories(
    cat_id: int,
    user: dict = require_perms("maint", [_PERM]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.category_service import list_subcategories as svc

    _assert_category_owned(db, cat_id)
    subs = svc(db, category_id=cat_id)
    return {
        "subcategories": [
            {"id": s.id, "name": s.name, "description": s.description}
            for s in subs
        ]
    }


@router.post("/categories/{cat_id}/subcategories", status_code=201)
def create_subcategory(
    cat_id: int,
    body: SubcategoryCreate,
    user: dict = require_perms("maint", [_PERM]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.category_service import create_subcategory as svc

    _assert_category_owned(db, cat_id)
    data = SimpleNamespace(
        name=body.name,
        description=body.description,
        display_order=0,
    )
    sub = svc(db, cat_id, data)
    return {"id": sub.id, "name": sub.name}


@router.patch("/subcategories/{sub_id}")
def update_subcategory(
    sub_id: int,
    body: SubcategoryUpdate,
    user: dict = require_perms("maint", [_PERM]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.category_service import update_subcategory as svc

    data = SimpleNamespace(
        name=body.name,
        description=body.description,
        display_order=None,
    )
    sub = svc(db, sub_id, data)
    return {"id": sub.id, "name": sub.name}


# ── Products ───────────────────────────────────────────────────────────────

@router.get("/products")
def list_products(
    search: Optional[str] = None,
    subcategory_id: Optional[int] = None,
    include_inactive: bool = False,
    user: dict = require_perms("maint", [_PERM]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.product_service import list_products as svc

    products = svc(
        db,
        department_code=_DEPT,
        include_inactive=include_inactive,
        search=search,
        subcategory_id=subcategory_id,
    )
    return {"products": products, "total": len(products)}


@router.get("/products/{product_id}")
def get_product(
    product_id: int,
    user: dict = require_perms("maint", [_PERM]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.product_service import get_product_with_stock

    return {"product": get_product_with_stock(db, product_id)}


@router.post("/products", status_code=201)
def create_product(
    body: ProductCreate,
    user: dict = require_perms("maint", [_PERM]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.product_service import create_product as svc

    user_id = int(user["sub"])
    # Service expects a data object with the product's attributes
    data = SimpleNamespace(
        name=body.name,
        unit_of_measure=body.unit_of_measure,
        subcategory_id=body.subcategory_id,
        department_code=_DEPT,
        description=body.description,
        restock_lead_time_days=body.lead_time_days,
        icon="bi-box",
    )
    product = svc(db, data, user_id)
    return {"id": product.id, "name": product.name}


@router.patch("/products/{product_id}")
def update_product(
    product_id: int,
    body: ProductUpdate,
    user: dict = require_perms("maint", [_PERM]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.product_service import update_product as svc

    data = SimpleNamespace(
        name=body.name,
        unit_of_measure=body.unit_of_measure,
        subcategory_id=body.subcategory_id,
        description=body.description,
        restock_lead_time_days=body.lead_time_days,
        icon=None,
    )
    product = svc(db, product_id, data)
    return {"id": product.id, "name": product.name}


# ── Stock Entries ──────────────────────────────────────────────────────────

@router.get("/stock-entries")
def list_entries(
    product_id: Optional[int] = None,
    include_voided: bool = False,
    page: int = 1,
    per_page: int = 20,
    user: dict = require_perms("maint", [_PERM]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.stock_service import list_entries as svc

    pag = svc(
        db,
        department_code=_DEPT,
        product_id=product_id,
        include_voided=include_voided,
        page=page,
        per_page=per_page,
    )

    def _entry_dict(e):
        return {
            "id": e.id,
            "product_id": e.product_id,
            "quantity_original": str(e.quantity_original),
            "quantity_remaining": str(e.quantity_remaining),
            "purchase_date": e.purchase_date.isoformat() if e.purchase_date else None,
            "purchase_folio": e.purchase_folio,
            "unit_cost": str(e.unit_cost),
            "supplier": e.supplier,
            "notes": e.notes,
            "voided": e.voided,
            "is_exhausted": e.is_exhausted,
            "registered_at": e.registered_at.isoformat() if e.registered_at else None,
        }

    return {
        "entries": [_entry_dict(e) for e in pag.items],
        "total": pag.total,
        "pages": pag.pages,
        "page": page,
    }


@router.post("/stock-entries", status_code=201)
def register_entry(
    body: StockEntryCreate,
    user: dict = require_perms("maint", [_PERM]),
    db: DbSession = None,
):
    from datetime import date as dt_date
    from itcj2.apps.warehouse.services.stock_service import register_entry as svc

    user_id = int(user["sub"])
    try:
        purchase_date = dt_date.fromisoformat(body.purchase_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Fecha inválida. Usa YYYY-MM-DD.")

    # Service expects a data object with entry attributes
    data = SimpleNamespace(
        product_id=body.product_id,
        quantity=body.quantity,
        unit_cost=body.unit_cost,
        purchase_folio=body.purchase_folio or "",
        supplier=body.supplier,
        purchase_date=purchase_date,
        notes=body.notes,
    )
    entry = svc(db, data, user_id)
    return {"id": entry.id, "quantity_original": str(entry.quantity_original)}


@router.post("/stock-entries/{entry_id}/void")
def void_entry(
    entry_id: int,
    body: VoidRequest,
    user: dict = require_perms("maint", [_PERM]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.stock_service import void_entry as svc

    user_id = int(user["sub"])
    svc(db, entry_id=entry_id, reason=body.reason, voided_by_id=user_id)
    return {"message": "Entrada anulada"}


# ── Movements ──────────────────────────────────────────────────────────────

@router.get("/movements")
def list_movements(
    product_id: Optional[int] = None,
    movement_type: Optional[str] = None,
    page: int = 1,
    per_page: int = 30,
    user: dict = require_perms("maint", [_PERM]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.models.movement import WarehouseMovement
    from itcj2.apps.warehouse.models.product import WarehouseProduct
    from itcj2.models.base import paginate

    query = (
        db.query(WarehouseMovement)
        .join(WarehouseProduct, WarehouseProduct.id == WarehouseMovement.product_id)
        .filter(WarehouseProduct.department_code == _DEPT)
    )
    if product_id:
        query = query.filter(WarehouseMovement.product_id == product_id)
    if movement_type:
        query = query.filter(WarehouseMovement.movement_type == movement_type)

    query = query.order_by(WarehouseMovement.performed_at.desc())
    pag = paginate(query, page=page, per_page=per_page)

    def _mv(m):
        return {
            "id": m.id,
            "product_id": m.product_id,
            "product_name": m.product.name if m.product else None,
            "movement_type": m.movement_type,
            "quantity": str(m.quantity),
            "source_app": m.source_app,
            "source_ticket_id": m.source_ticket_id,
            "notes": m.notes,
            "performed_at": m.performed_at.isoformat() if m.performed_at else None,
        }

    return {
        "movements": [_mv(m) for m in pag.items],
        "total": pag.total,
        "pages": pag.pages,
        "page": page,
    }
