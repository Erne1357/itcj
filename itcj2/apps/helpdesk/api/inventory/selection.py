"""
Inventory Selection API v2 — 4 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/inventory/inventory_selection.py
"""
from fastapi import APIRouter, HTTPException, Request
from itcj2.dependencies import DbSession, require_app

router = APIRouter(tags=["helpdesk-inventory-selection"])


def _get_status_color(status: str) -> str:
    colors = {
        "ACTIVE": "success", "PENDING_ASSIGNMENT": "warning", "MAINTENANCE": "info",
        "DAMAGED": "danger", "RETIRED": "secondary", "LOST": "dark",
    }
    return colors.get(status, "secondary")


def _get_item_badge(item) -> dict:
    if item.is_assigned_to_user:
        return {"text": "Asignado", "color": "primary"}
    elif item.is_in_group:
        return {"text": item.group.name if item.group else "Grupo", "color": "info"}
    elif item.is_pending_assignment:
        return {"text": "Pendiente", "color": "warning"}
    return {"text": "Disponible", "color": "success"}


@router.get("/for-ticket")
def get_items_for_ticket(
    request: Request,
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    from itcj.apps.helpdesk.models import InventoryItem
    from sqlalchemy import and_, or_

    user_id = int(user["sub"])
    params = request.query_params

    department_id = params.get("department_id", type=None)
    if department_id:
        department_id = int(department_id)
    else:
        from itcj.core.services.departments_service import get_user_department
        user_dept = get_user_department(user_id)
        if user_dept:
            department_id = user_dept.id

    if not department_id:
        return {"success": True, "data": []}

    category_id = params.get("category_id")
    group_id = params.get("group_id")
    search = params.get("search")

    include_user = params.get("include_user_equipment", "true").lower() == "true"
    include_dept = params.get("include_department_equipment", "true").lower() == "true"
    include_group = params.get("include_group_equipment", "true").lower() == "true"

    query = InventoryItem.query.filter(
        InventoryItem.department_id == department_id,
        InventoryItem.status == "ACTIVE",
        InventoryItem.is_active == True,
    )

    scope_filters = []
    if include_user:
        scope_filters.append(InventoryItem.assigned_to_user_id == user_id)
    if include_dept:
        scope_filters.append(and_(InventoryItem.assigned_to_user_id.is_(None), InventoryItem.group_id.is_(None)))
    if include_group:
        scope_filters.append(InventoryItem.group_id.isnot(None))

    if scope_filters:
        query = query.filter(or_(*scope_filters))

    if category_id:
        query = query.filter(InventoryItem.category_id == int(category_id))
    if group_id:
        query = query.filter(InventoryItem.group_id == int(group_id))

    if search:
        search_term = f"%{search}%"
        query = query.filter(or_(
            InventoryItem.inventory_number.ilike(search_term),
            InventoryItem.brand.ilike(search_term),
            InventoryItem.model.ilike(search_term),
            InventoryItem.location_detail.ilike(search_term),
        ))

    items = query.order_by(InventoryItem.group_id.asc().nullsfirst(), InventoryItem.inventory_number).all()

    result = []
    for item in items:
        item_data = item.to_dict(include_relations=True)
        item_data["visual"] = {
            "icon": item.category.icon if item.category else "fas fa-laptop",
            "color": _get_status_color(item.status),
            "badge": _get_item_badge(item),
        }
        result.append(item_data)

    return {"success": True, "data": result, "total": len(result)}


@router.get("/by-group/{group_id}")
def get_items_by_group(
    group_id: int,
    category_id: int | None = None,
    status: str = "ACTIVE",
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    from itcj.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj.apps.helpdesk.models import InventoryItem, InventoryGroup

    user_id = int(user["sub"])

    group = InventoryGroup.query.get(group_id)
    if not group or not group.is_active:
        raise HTTPException(404, detail={"success": False, "error": "Grupo no encontrado"})

    user_roles = user_roles_in_app(user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(["secretary_comp_center"])
    if "admin" not in user_roles and user_id not in secretary_comp_center and "tech_desarrollo" not in user_roles and "tech_soporte" not in user_roles:
        from itcj.core.services.departments_service import get_user_department
        user_dept = get_user_department(user_id)
        if not user_dept or user_dept.id != group.department_id:
            raise HTTPException(403, detail={"success": False, "error": "No tiene permiso para ver este grupo"})

    query = InventoryItem.query.filter(
        InventoryItem.group_id == group_id, InventoryItem.status == status, InventoryItem.is_active == True,
    )
    if category_id:
        query = query.filter(InventoryItem.category_id == category_id)

    items = query.order_by(InventoryItem.inventory_number).all()

    items_by_category = {}
    for item in items:
        cat_id = item.category_id
        if cat_id not in items_by_category:
            items_by_category[cat_id] = {"category": item.category.to_dict() if item.category else None, "items": []}

        item_data = item.to_dict(include_relations=True)
        item_data["visual"] = {
            "icon": item.category.icon if item.category else "fas fa-laptop",
            "color": _get_status_color(item.status),
            "badge": _get_item_badge(item),
        }
        items_by_category[cat_id]["items"].append(item_data)

    return {
        "success": True,
        "group": group.to_dict(include_capacities=True),
        "items_by_category": list(items_by_category.values()),
        "total": len(items),
    }


@router.get("/groups-with-items")
def get_groups_with_items(
    department_id: int | None = None,
    category_id: int | None = None,
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    from itcj.apps.helpdesk.models import InventoryItem, InventoryGroup

    user_id = int(user["sub"])

    dept_id = department_id
    if not dept_id:
        from itcj.core.services.departments_service import get_user_department
        user_dept = get_user_department(user_id)
        if user_dept:
            dept_id = user_dept.id

    if not dept_id:
        return {"success": True, "data": []}

    groups = InventoryGroup.query.filter(
        InventoryGroup.department_id == dept_id, InventoryGroup.is_active == True,
    ).order_by(InventoryGroup.name).all()

    result = []
    for group in groups:
        item_query = InventoryItem.query.filter(
            InventoryItem.group_id == group.id, InventoryItem.status == "ACTIVE", InventoryItem.is_active == True,
        )
        if category_id:
            item_query = item_query.filter(InventoryItem.category_id == category_id)

        items_count = item_query.count()
        if items_count > 0:
            group_data = group.to_dict(include_capacities=False)
            group_data["items_count"] = items_count
            result.append(group_data)

    return {"success": True, "data": result}


@router.post("/validate-for-ticket")
def validate_items_for_ticket(
    body: dict,
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    from itcj.apps.helpdesk.models import InventoryItem

    if not body.get("item_ids") or not isinstance(body["item_ids"], list):
        raise HTTPException(400, detail={"success": False, "error": "item_ids (array) requerido"})

    items = []
    invalid = []
    departments = set()

    for item_id in body["item_ids"]:
        item = InventoryItem.query.get(item_id)
        if not item or not item.is_active:
            invalid.append({"item_id": item_id, "reason": "Equipo no encontrado o inactivo"})
            continue
        if item.status not in ["ACTIVE", "MAINTENANCE"]:
            invalid.append({"item_id": item_id, "reason": f"Estado no válido: {item.status}"})
            continue
        items.append(item.to_dict(include_relations=True))
        departments.add(item.department_id)

    multi_dept_warning = "Los equipos pertenecen a diferentes departamentos" if len(departments) > 1 else None

    return {
        "success": len(invalid) == 0,
        "valid_items": items,
        "invalid_items": invalid,
        "warning": multi_dept_warning,
        "summary": {"total_requested": len(body["item_ids"]), "valid": len(items), "invalid": len(invalid)},
    }
