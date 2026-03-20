"""
Warehouse — Stock Entries API
GET    /stock-entries
POST   /stock-entries
GET    /stock-entries/{id}
POST   /stock-entries/{id}/void
"""
import logging

from fastapi import APIRouter

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.warehouse.schemas.stock import StockEntryCreate, StockEntryVoidRequest
from itcj2.apps.warehouse.services.utils import resolve_dept_code

router = APIRouter(tags=["warehouse-entries"])
logger = logging.getLogger(__name__)


@router.get("/stock-entries")
def list_entries(
    product_id: int | None = None,
    include_voided: bool = False,
    page: int = 1,
    per_page: int = 20,
    dept: str | None = None,
    user: dict = require_perms("warehouse", ["warehouse.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.stock_service import list_entries as svc_list

    department_code = resolve_dept_code(db, user, dept)
    result = svc_list(db, product_id, department_code, include_voided, page, per_page)

    return {
        "entries": [
            {
                "id": e.id,
                "product_id": e.product_id,
                "quantity_original": e.quantity_original,
                "quantity_remaining": e.quantity_remaining,
                "purchase_date": e.purchase_date.isoformat(),
                "purchase_folio": e.purchase_folio,
                "unit_cost": e.unit_cost,
                "supplier": e.supplier,
                "is_exhausted": e.is_exhausted,
                "voided": e.voided,
                "registered_at": e.registered_at.isoformat(),
            }
            for e in result.items
        ],
        "total": result.total,
        "page": result.page,
        "pages": result.pages,
        "has_next": result.has_next,
    }


@router.post("/stock-entries", status_code=201)
def register_entry(
    body: StockEntryCreate,
    user: dict = require_perms("warehouse", ["warehouse.api.entries.create"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.stock_service import register_entry as svc_register

    user_id = int(user["sub"])
    entry = svc_register(db, body, user_id)
    db.commit()

    logger.info(
        "Entrada de stock registrada: producto=%s folio=%s qty=%s por usuario=%s",
        body.product_id, body.purchase_folio, body.quantity, user_id,
    )
    return {
        "message": "Entrada de stock registrada exitosamente",
        "entry": {
            "id": entry.id,
            "product_id": entry.product_id,
            "quantity_original": entry.quantity_original,
            "purchase_folio": entry.purchase_folio,
        },
    }


@router.get("/stock-entries/{entry_id}")
def get_entry(
    entry_id: int,
    user: dict = require_perms("warehouse", ["warehouse.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.stock_service import get_entry as svc_get

    entry = svc_get(db, entry_id)
    return {
        "entry": {
            "id": entry.id,
            "product_id": entry.product_id,
            "quantity_original": entry.quantity_original,
            "quantity_remaining": entry.quantity_remaining,
            "purchase_date": entry.purchase_date.isoformat(),
            "purchase_folio": entry.purchase_folio,
            "unit_cost": entry.unit_cost,
            "supplier": entry.supplier,
            "notes": entry.notes,
            "is_exhausted": entry.is_exhausted,
            "voided": entry.voided,
            "voided_at": entry.voided_at.isoformat() if entry.voided_at else None,
            "void_reason": entry.void_reason,
            "registered_at": entry.registered_at.isoformat(),
        }
    }


@router.post("/stock-entries/{entry_id}/void")
def void_entry(
    entry_id: int,
    body: StockEntryVoidRequest,
    user: dict = require_perms("warehouse", ["warehouse.api.entries.void"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.stock_service import void_entry as svc_void

    user_id = int(user["sub"])
    svc_void(db, entry_id, body.reason, user_id)
    db.commit()

    logger.info("Entrada %s anulada por usuario %s", entry_id, user_id)
    return {"message": "Entrada de stock anulada exitosamente"}
