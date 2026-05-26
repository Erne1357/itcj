"""Categories API — maint (admin)."""
import logging

from fastapi import APIRouter, Request

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.maint.services.config_audit_service import log_config_change, client_ip
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
    request: Request,
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
    # Registrar auditoría en transacción separada (el service ya hizo commit)
    try:
        log_config_change(
            db=db,
            user_id=int(user["sub"]),
            entity_type="category",
            entity_id=category.id,
            action="create",
            before=None,
            after={"id": category.id, "code": category.code, "name": category.name},
            ip=client_ip(request),
        )
        db.commit()
    except Exception:
        db.rollback()
    return {"category_id": category.id, "code": category.code}


@router.patch("/{category_id}")
async def update_category(
    category_id: int,
    request: Request,
    body: UpdateCategoryRequest,
    user: dict = require_perms("maint", ["maint.admin.api.categories"]),
    db: DbSession = None,
):
    # Capturar before antes de que el service modifique
    from itcj2.apps.maint.models.category import MaintCategory
    _cat = db.get(MaintCategory, category_id)
    before = {"id": _cat.id, "name": _cat.name, "icon": _cat.icon, "display_order": _cat.display_order} if _cat else None

    result = category_service.update_category(
        db=db,
        category_id=category_id,
        name=body.name,
        description=body.description,
        icon=body.icon,
        display_order=body.display_order,
    )
    try:
        log_config_change(
            db=db,
            user_id=int(user["sub"]),
            entity_type="category",
            entity_id=category_id,
            action="update",
            before=before,
            after={"id": result.id, "name": result.name, "icon": result.icon, "display_order": result.display_order},
            ip=client_ip(request),
        )
        db.commit()
    except Exception:
        db.rollback()
    return result


@router.patch("/{category_id}/toggle")
async def toggle_category(
    category_id: int,
    request: Request,
    body: ToggleCategoryRequest,
    user: dict = require_perms("maint", ["maint.admin.api.categories"]),
    db: DbSession = None,
):
    from itcj2.apps.maint.models.category import MaintCategory
    _cat = db.get(MaintCategory, category_id)
    before = {"id": _cat.id, "is_active": _cat.is_active} if _cat else None

    result = category_service.toggle_category(db, category_id, body.is_active)
    try:
        log_config_change(
            db=db,
            user_id=int(user["sub"]),
            entity_type="category",
            entity_id=category_id,
            action="toggle",
            before=before,
            after={"id": result.id, "is_active": result.is_active},
            ip=client_ip(request),
        )
        db.commit()
    except Exception:
        db.rollback()
    return result


@router.put("/{category_id}/field-template")
async def update_field_template(
    category_id: int,
    request: Request,
    body: UpdateFieldTemplateRequest,
    user: dict = require_perms("maint", ["maint.admin.api.categories"]),
    db: DbSession = None,
):
    # Capturar estado previo antes de que el service haga commit
    from itcj2.apps.maint.models.category import MaintCategory
    _cat = db.get(MaintCategory, category_id)
    before_template = _cat.field_template if _cat else None

    result = category_service.update_field_template(db, category_id, body.fields)

    # Registrar auditoría en transacción separada (el service ya hizo commit)
    try:
        log_config_change(
            db=db,
            user_id=int(user["sub"]),
            entity_type="field_template",
            entity_id=category_id,
            action="update",
            before={"fields": before_template},
            after={"fields": result.field_template if hasattr(result, "field_template") else None},
            ip=client_ip(request),
        )
        db.commit()
    except Exception:
        db.rollback()
    return result
