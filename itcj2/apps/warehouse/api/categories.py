"""
Warehouse — Categories API
GET    /categories
POST   /categories
PATCH  /categories/{id}
DELETE /categories/{id}
GET    /categories/{id}/subcategories
POST   /categories/{id}/subcategories
PATCH  /subcategories/{id}
DELETE /subcategories/{id}
"""
import logging

from fastapi import APIRouter, HTTPException

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.warehouse.schemas.categories import (
    WarehouseCategoryCreate,
    WarehouseCategoryUpdate,
    WarehouseSubcategoryCreate,
    WarehouseSubcategoryUpdate,
)
from itcj2.apps.warehouse.services.utils import resolve_dept_code

router = APIRouter(tags=["warehouse-categories"])
logger = logging.getLogger(__name__)


@router.get("/categories")
def list_categories(
    include_inactive: bool = False,
    with_subcategories: bool = False,
    dept: str | None = None,
    user: dict = require_perms("warehouse", ["warehouse.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.category_service import list_categories as svc_list

    department_code = resolve_dept_code(db, user, dept)
    categories = svc_list(db, department_code, include_inactive, with_subcategories)

    def _cat_dict(c):
        d = {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "icon": c.icon,
            "department_code": c.department_code,
            "is_active": c.is_active,
            "display_order": c.display_order,
        }
        if with_subcategories:
            d["subcategories"] = [
                {
                    "id": s.id,
                    "name": s.name,
                    "is_active": s.is_active,
                    "display_order": s.display_order,
                }
                for s in c.subcategories
                if include_inactive or s.is_active
            ]
        return d

    return {"categories": [_cat_dict(c) for c in categories], "total": len(categories)}


@router.post("/categories", status_code=201)
def create_category(
    body: WarehouseCategoryCreate,
    dept: str | None = None,
    user: dict = require_perms("warehouse", ["warehouse.api.categories.manage"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.category_service import create_category as svc_create

    department_code = resolve_dept_code(db, user, dept)
    category = svc_create(db, body, department_code)
    db.commit()

    return {
        "message": "Categoría creada exitosamente",
        "category": {"id": category.id, "name": category.name, "code": category.department_code},
    }


@router.patch("/categories/{category_id}")
def update_category(
    category_id: int,
    body: WarehouseCategoryUpdate,
    user: dict = require_perms("warehouse", ["warehouse.api.categories.manage"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.category_service import update_category as svc_update

    category = svc_update(db, category_id, body)
    db.commit()
    return {"message": "Categoría actualizada", "category": {"id": category.id, "name": category.name}}


@router.delete("/categories/{category_id}")
def deactivate_category(
    category_id: int,
    user: dict = require_perms("warehouse", ["warehouse.api.categories.manage"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.category_service import deactivate_category as svc_deactivate

    svc_deactivate(db, category_id)
    db.commit()
    return {"message": "Categoría desactivada exitosamente"}


# ── Subcategorías ─────────────────────────────────────────────────────────────

@router.get("/categories/{category_id}/subcategories")
def list_subcategories(
    category_id: int,
    include_inactive: bool = False,
    user: dict = require_perms("warehouse", ["warehouse.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.category_service import list_subcategories as svc_list

    subcategories = svc_list(db, category_id, include_inactive)
    return {
        "subcategories": [
            {
                "id": s.id,
                "category_id": s.category_id,
                "name": s.name,
                "description": s.description,
                "is_active": s.is_active,
                "display_order": s.display_order,
            }
            for s in subcategories
        ],
        "total": len(subcategories),
    }


@router.post("/categories/{category_id}/subcategories", status_code=201)
def create_subcategory(
    category_id: int,
    body: WarehouseSubcategoryCreate,
    user: dict = require_perms("warehouse", ["warehouse.api.categories.manage"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.category_service import create_subcategory as svc_create

    sub = svc_create(db, category_id, body)
    db.commit()
    return {"message": "Subcategoría creada exitosamente", "subcategory": {"id": sub.id, "name": sub.name}}


@router.patch("/subcategories/{subcategory_id}")
def update_subcategory(
    subcategory_id: int,
    body: WarehouseSubcategoryUpdate,
    user: dict = require_perms("warehouse", ["warehouse.api.categories.manage"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.category_service import update_subcategory as svc_update

    sub = svc_update(db, subcategory_id, body)
    db.commit()
    return {"message": "Subcategoría actualizada", "subcategory": {"id": sub.id, "name": sub.name}}


@router.delete("/subcategories/{subcategory_id}")
def deactivate_subcategory(
    subcategory_id: int,
    user: dict = require_perms("warehouse", ["warehouse.api.categories.manage"]),
    db: DbSession = None,
):
    from itcj2.apps.warehouse.services.category_service import deactivate_subcategory as svc_deactivate

    svc_deactivate(db, subcategory_id)
    db.commit()
    return {"message": "Subcategoría desactivada exitosamente"}
