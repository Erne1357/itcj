"""Categories API — maint (admin)."""
import logging

from fastapi import APIRouter

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.maint.schemas.categories import (
    CreateCategoryRequest,
    UpdateCategoryRequest,
    ToggleCategoryRequest,
    UpdateFieldTemplateRequest,
)
from itcj2.apps.maint.services import category_service

router = APIRouter(tags=["maint-categories"])
logger = logging.getLogger(__name__)


@router.get("")
@router.get("/")
async def list_categories(
    only_active: bool = True,
    user: dict = require_perms("maint", [
        "maint.tickets.api.create",   # Solicitantes necesitan ver categorías activas
        "maint.admin.api.categories",
    ]),
    db: DbSession = None,
):
    categories = category_service.list_categories(db, only_active=only_active)
    return {
        "categories": [
            {
                "id": c.id,
                "code": c.code,
                "name": c.name,
                "description": c.description,
                "icon": c.icon,
                "field_template": c.field_template or [],
                "is_active": c.is_active,
                "display_order": c.display_order,
            }
            for c in categories
        ]
    }


@router.post("", status_code=201)
async def create_category(
    body: CreateCategoryRequest,
    user: dict = require_perms("maint", ["maint.admin.api.categories"]),
    db: DbSession = None,
):
    category = category_service.create_category(
        db=db,
        code=body.code,
        name=body.name,
        description=body.description,
        icon=body.icon,
        field_template=body.field_template,
        display_order=body.display_order or 0,
    )
    return {"category_id": category.id, "code": category.code}


@router.patch("/{category_id}")
async def update_category(
    category_id: int,
    body: UpdateCategoryRequest,
    user: dict = require_perms("maint", ["maint.admin.api.categories"]),
    db: DbSession = None,
):
    return category_service.update_category(
        db=db,
        category_id=category_id,
        name=body.name,
        description=body.description,
        icon=body.icon,
        display_order=body.display_order,
    )


@router.patch("/{category_id}/toggle")
async def toggle_category(
    category_id: int,
    body: ToggleCategoryRequest,
    user: dict = require_perms("maint", ["maint.admin.api.categories"]),
    db: DbSession = None,
):
    return category_service.toggle_category(db, category_id, body.is_active)


@router.put("/{category_id}/field-template")
async def update_field_template(
    category_id: int,
    body: UpdateFieldTemplateRequest,
    user: dict = require_perms("maint", ["maint.admin.api.categories"]),
    db: DbSession = None,
):
    return category_service.update_field_template(db, category_id, body.fields)
