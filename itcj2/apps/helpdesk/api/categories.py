"""
Categories API v2 — 10 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/categories.py
"""
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.helpdesk.schemas.categories import (
    CreateCategoryRequest,
    UpdateCategoryRequest,
    ToggleCategoryRequest,
    ReorderCategoriesRequest,
    UpdateFieldTemplateRequest,
)

router = APIRouter(tags=["helpdesk-categories"])
logger = logging.getLogger(__name__)


@router.get("")
def list_categories(
    area: str | None = None,
    active: str | None = None,
    include_inactive: str = "false",
    user: dict = require_perms("helpdesk", ["helpdesk.categories.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import Category

    query = db.query(Category)

    if area:
        from itcj2.apps.helpdesk.utils.catalog_cache import get_area_codes
        valid_areas = get_area_codes(db, active_only=False)
        if area not in valid_areas:
            raise HTTPException(400, detail={"error": "invalid_area", "message": f"El área debe ser una de: {sorted(valid_areas)}"})
        query = query.filter_by(area=area)

    if active is not None:
        query = query.filter_by(is_active=active.lower() == "true")
    elif include_inactive.lower() != "true":
        query = query.filter_by(is_active=True)

    categories = query.order_by(Category.area, Category.display_order).all()

    grouped = {"DESARROLLO": [], "SOPORTE": []}
    for cat in categories:
        grouped[cat.area].append(cat.to_dict())

    return {
        "categories": [cat.to_dict() for cat in categories],
        "grouped": grouped,
        "total": len(categories),
    }


@router.get("/stats")
def get_categories_stats(
    user: dict = require_perms("helpdesk", ["helpdesk.categories.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import Category, Ticket
    from sqlalchemy import case, func

    stats = db.query(
        Category.id, Category.name, Category.area, Category.is_active,
        func.count(Ticket.id).label("tickets_count"),
        func.count(case((Ticket.status.notin_(["CLOSED", "CANCELED"]), Ticket.id))).label("active_tickets_count"),
    ).outerjoin(Ticket, Ticket.category_id == Category.id).group_by(
        Category.id, Category.name, Category.area, Category.is_active
    ).order_by(Category.area, Category.display_order).all()

    categories_stats = [
        {"id": s.id, "name": s.name, "area": s.area, "is_active": s.is_active, "tickets_count": s.tickets_count, "active_tickets_count": s.active_tickets_count}
        for s in stats
    ]

    grouped = {
        "DESARROLLO": [s for s in categories_stats if s["area"] == "DESARROLLO"],
        "SOPORTE": [s for s in categories_stats if s["area"] == "SOPORTE"],
    }

    return {"categories": categories_stats, "grouped": grouped}


@router.get("/{category_id}")
def get_category(
    category_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.categories.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import Category, Ticket

    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(404, detail={"error": "not_found", "message": "Categoría no encontrada"})

    tickets_count = db.query(Ticket).filter_by(category_id=category_id).count()
    data = category.to_dict()
    data["tickets_count"] = tickets_count

    return {"category": data}


@router.post("", status_code=201)
def create_category(
    request: Request,
    body: CreateCategoryRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.categories.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import Category
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change
    from sqlalchemy import func

    user_id = int(user["sub"])
    client_ip = request.client.host if request.client else None

    from itcj2.apps.helpdesk.utils.catalog_cache import get_area_codes
    valid_areas = get_area_codes(db, active_only=True)
    if body.area not in valid_areas:
        raise HTTPException(400, detail={"error": "invalid_area", "message": f"El área debe ser una de: {sorted(valid_areas)}"})

    existing = db.query(Category).filter_by(code=body.code).first()
    if existing:
        raise HTTPException(409, detail={"error": "code_exists", "message": f'Ya existe una categoría con el código "{body.code}"'})

    if body.display_order is None:
        max_order = db.query(func.max(Category.display_order)).filter_by(area=body.area).scalar()
        display_order = (max_order or 0) + 1
    else:
        display_order = body.display_order

    category = Category(
        area=body.area,
        code=body.code.strip().lower(),
        name=body.name.strip(),
        description=body.description.strip() if body.description else None,
        display_order=display_order,
        is_active=True,
    )

    db.add(category)
    db.flush()  # garantiza category.id antes del log

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="category",
        entity_id=category.id,
        action="create",
        before=None,
        after=category.to_dict(),
        ip_address=client_ip,
    )

    db.commit()

    logger.info(f"Categoría '{category.name}' creada por usuario {user_id}")
    return {"message": "Categoría creada exitosamente", "category": category.to_dict()}


@router.patch("/{category_id}")
def update_category(
    category_id: int,
    request: Request,
    body: UpdateCategoryRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.categories.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import Category
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change

    user_id = int(user["sub"])
    client_ip = request.client.host if request.client else None

    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(404, detail={"error": "not_found", "message": "Categoría no encontrada"})

    before = category.to_dict()

    if body.name is not None:
        name = body.name.strip()
        if len(name) < 2:
            raise HTTPException(400, detail={"error": "invalid_name", "message": "El nombre debe tener al menos 2 caracteres"})
        category.name = name

    if body.description is not None:
        category.description = body.description.strip() if body.description else None

    if body.display_order is not None:
        if not isinstance(body.display_order, int) or body.display_order < 0:
            raise HTTPException(400, detail={"error": "invalid_display_order", "message": "El display_order debe ser un número entero positivo"})
        category.display_order = body.display_order

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="category",
        entity_id=category.id,
        action="update",
        before=before,
        after=category.to_dict(),
        ip_address=client_ip,
    )

    db.commit()
    logger.info(f"Categoría {category_id} actualizada por usuario {user_id}")
    return {"message": "Categoría actualizada exitosamente", "category": category.to_dict()}


@router.post("/{category_id}/toggle")
def toggle_category(
    category_id: int,
    request: Request,
    body: ToggleCategoryRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.categories.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import Category, Ticket
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change

    user_id = int(user["sub"])
    client_ip = request.client.host if request.client else None

    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(404, detail={"error": "not_found", "message": "Categoría no encontrada"})

    if not body.is_active and category.is_active:
        active_tickets = db.query(Ticket).filter(
            Ticket.category_id == category_id,
            Ticket.status.notin_(["CLOSED", "CANCELED"]),
        ).count()
        if active_tickets > 0:
            raise HTTPException(400, detail={
                "error": "has_active_tickets",
                "message": f"No se puede desactivar. Hay {active_tickets} ticket(s) activo(s)",
                "active_tickets_count": active_tickets,
            })

    before = category.to_dict()
    category.is_active = body.is_active

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="category",
        entity_id=category.id,
        action="toggle",
        before=before,
        after=category.to_dict(),
        ip_address=client_ip,
    )

    db.commit()

    action = "activada" if body.is_active else "desactivada"
    logger.info(f"Categoría {category_id} {action} por usuario {user_id}")
    return {"message": f"Categoría {action} exitosamente", "category": category.to_dict()}


@router.post("/reorder")
def reorder_categories(
    request: Request,
    body: ReorderCategoriesRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.categories.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import Category
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change

    user_id = int(user["sub"])
    client_ip = request.client.host if request.client else None

    from itcj2.apps.helpdesk.utils.catalog_cache import get_area_codes
    valid_areas = get_area_codes(db, active_only=False)
    if body.area not in valid_areas:
        raise HTTPException(400, detail={"error": "invalid_area", "message": f"El área debe ser una de: {sorted(valid_areas)}"})

    before_snapshot = []
    for item in body.order:
        if "id" not in item or "display_order" not in item:
            raise HTTPException(400, detail={"error": "invalid_order_item", "message": "Cada item debe tener id y display_order"})
        category = db.get(Category, item["id"])
        if not category:
            raise HTTPException(404, detail={"error": "category_not_found", "message": f'Categoría con id {item["id"]} no encontrada'})
        if category.area != body.area:
            raise HTTPException(400, detail={"error": "area_mismatch", "message": f"La categoría {category.name} no pertenece al área {body.area}"})
        before_snapshot.append({"id": category.id, "name": category.name, "display_order": category.display_order})
        category.display_order = item["display_order"]

    after_snapshot = [{"id": item["id"], "display_order": item["display_order"]} for item in body.order]

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="category",
        entity_id=None,
        action="reorder",
        before={"area": body.area, "previous_order": before_snapshot},
        after={"area": body.area, "order": after_snapshot},
        ip_address=client_ip,
    )

    db.commit()
    logger.info(f"Categorías del área {body.area} reordenadas por usuario {user_id}")

    categories = db.query(Category).filter_by(area=body.area).order_by(Category.display_order).all()
    return {"message": "Orden actualizado exitosamente", "categories": [cat.to_dict() for cat in categories]}


@router.delete("/{category_id}")
def delete_category(
    category_id: int,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.categories.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import Category, Ticket
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change

    user_id = int(user["sub"])
    client_ip = request.client.host if request.client else None

    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(404, detail={"error": "not_found", "message": "Categoría no encontrada"})

    tickets_count = db.query(Ticket).filter_by(category_id=category_id).count()
    if tickets_count > 0:
        raise HTTPException(400, detail={
            "error": "has_tickets",
            "message": f"No se puede eliminar. Hay {tickets_count} ticket(s) asociado(s)",
            "tickets_count": tickets_count,
        })

    before = category.to_dict()
    category.is_active = False

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="category",
        entity_id=category.id,
        action="delete",
        before=before,
        after=None,
        ip_address=client_ip,
    )

    db.commit()

    logger.info(f"Categoría {category_id} eliminada (soft delete) por usuario {user_id}")
    return {"message": "Categoría eliminada exitosamente"}


@router.get("/{category_id}/field-template")
def get_category_field_template(
    category_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.categories.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import Category

    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(404, detail={"error": "not_found", "message": "Categoría no encontrada"})

    field_template = category.field_template or {"enabled": False, "fields": []}
    return {"category_id": category_id, "category_name": category.name, "field_template": field_template}


@router.put("/{category_id}/field-template")
def update_category_field_template(
    category_id: int,
    request: Request,
    body: UpdateFieldTemplateRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.categories.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import Category
    from itcj2.apps.helpdesk.services.config_audit_service import log_config_change

    user_id = int(user["sub"])
    client_ip = request.client.host if request.client else None

    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(404, detail={"error": "not_found", "message": "Categoría no encontrada"})

    before = {"field_template": category.field_template}

    category.field_template = body.model_dump()
    category.updated_at = datetime.now()

    log_config_change(
        db=db,
        user_id=user_id,
        entity_type="field_template",
        entity_id=category_id,
        action="update",
        before=before,
        after={"field_template": body.model_dump()},
        ip_address=client_ip,
    )

    db.commit()

    logger.info(f"Field template para categoría {category_id} actualizado por usuario {user_id}")
    return {"message": "Plantilla de campos actualizada exitosamente", "field_template": category.field_template}
