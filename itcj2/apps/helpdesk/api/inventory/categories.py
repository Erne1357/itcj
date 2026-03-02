"""
Inventory Categories API v2 — 6 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/inventory/inventory_categories.py
"""
from fastapi import APIRouter, HTTPException
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["helpdesk-inventory-categories"])


@router.get("")
def get_categories(
    active: str | None = None,
    with_count: str = "false",
    user: dict = require_perms("helpdesk", ["helpdesk.inventory_categories.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import InventoryCategory, InventoryItem
    from sqlalchemy import func

    query = InventoryCategory.query
    if active is not None:
        query = query.filter(InventoryCategory.is_active == (active.lower() == "true"))

    query = query.order_by(InventoryCategory.display_order, InventoryCategory.name)
    categories = query.all()

    result = []
    for category in categories:
        data = category.to_dict()
        if with_count.lower() == "true":
            count = db.query(func.count(InventoryItem.id)).filter(
                InventoryItem.category_id == category.id, InventoryItem.is_active == True
            ).scalar()
            data["items_count"] = count
        result.append(data)

    return {"success": True, "data": result, "total": len(result)}


@router.get("/{category_id}")
def get_category(
    category_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory_categories.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import InventoryCategory

    category = InventoryCategory.query.get(category_id)
    if not category:
        raise HTTPException(404, detail={"success": False, "error": "Categoría no encontrada"})

    return {"success": True, "data": category.to_dict()}


@router.post("", status_code=201)
def create_category(
    body: dict,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory_categories.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import InventoryCategory

    if not body.get("code"):
        raise HTTPException(400, detail={"success": False, "error": "El código es requerido"})
    if not body.get("name"):
        raise HTTPException(400, detail={"success": False, "error": "El nombre es requerido"})
    if not body.get("inventory_prefix"):
        raise HTTPException(400, detail={"success": False, "error": "El prefijo de inventario es requerido"})

    prefix = body["inventory_prefix"].upper().strip()
    if len(prefix) < 2 or len(prefix) > 10:
        raise HTTPException(400, detail={"success": False, "error": "El prefijo debe tener entre 2 y 10 caracteres"})

    existing = InventoryCategory.query.filter_by(code=body["code"]).first()
    if existing:
        raise HTTPException(409, detail={"success": False, "error": f"El código '{body['code']}' ya existe"})

    category = InventoryCategory(
        code=body["code"], name=body["name"],
        description=body.get("description"),
        icon=body.get("icon", "fas fa-box"),
        is_active=body.get("is_active", True),
        requires_specs=body.get("requires_specs", True),
        spec_template=body.get("spec_template"),
        display_order=body.get("display_order", 0),
        inventory_prefix=prefix,
    )
    db.add(category)
    db.commit()

    return {"success": True, "message": "Categoría creada exitosamente", "data": category.to_dict()}


@router.patch("/{category_id}")
def update_category(
    category_id: int,
    body: dict,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory_categories.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import InventoryCategory

    category = InventoryCategory.query.get(category_id)
    if not category:
        raise HTTPException(404, detail={"success": False, "error": "Categoría no encontrada"})

    for field in ("name", "description", "icon", "requires_specs", "spec_template", "display_order", "is_active"):
        if field in body:
            setattr(category, field, body[field])

    db.commit()
    return {"success": True, "message": "Categoría actualizada exitosamente", "data": category.to_dict()}


@router.post("/{category_id}/toggle")
def toggle_category(
    category_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory_categories.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import InventoryCategory

    category = InventoryCategory.query.get(category_id)
    if not category:
        raise HTTPException(404, detail={"success": False, "error": "Categoría no encontrada"})

    category.is_active = not category.is_active
    db.commit()

    status_text = "activada" if category.is_active else "desactivada"
    return {"success": True, "message": f"Categoría {status_text} exitosamente", "data": {"id": category.id, "is_active": category.is_active}}


@router.post("/reorder")
def reorder_categories(
    body: dict,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory_categories.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import InventoryCategory

    if not body.get("categories"):
        raise HTTPException(400, detail={"success": False, "error": "Se requiere el array de categorías"})

    for item in body["categories"]:
        category = InventoryCategory.query.get(item["id"])
        if category:
            category.display_order = item["display_order"]

    db.commit()
    return {"success": True, "message": "Orden actualizado exitosamente"}
