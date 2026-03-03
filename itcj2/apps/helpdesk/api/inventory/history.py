"""
Inventory History API v2 — 5 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/inventory/inventory_history.py
"""
from fastapi import APIRouter, HTTPException
from itcj2.dependencies import DbSession, require_perms, require_app

router = APIRouter(tags=["helpdesk-inventory-history"])


@router.get("/item/{item_id}")
def get_item_history(
    item_id: int,
    limit: int = 50,
    event_types: str | None = None,
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj2.apps.helpdesk.models import InventoryItem
    from itcj2.apps.helpdesk.services.inventory_history_service import InventoryHistoryService

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])

    item = db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    if "admin" not in user_roles and user_id not in secretary_comp_center and "tech_desarrollo" not in user_roles and "tech_soporte" not in user_roles:
        if "department_head" in user_roles:
            from itcj2.core.services.departments_service import get_user_department
            user_dept = get_user_department(db, user_id)
            if not user_dept or item.department_id != user_dept.id:
                raise HTTPException(403, detail={"success": False, "error": "No tiene permiso para ver el historial de este equipo"})
        else:
            if item.assigned_to_user_id != user_id:
                raise HTTPException(403, detail={"success": False, "error": "No tiene permiso para ver el historial de este equipo"})

    event_types_list = event_types.split(",") if event_types else None
    history = InventoryHistoryService.get_item_history(item_id=item_id, limit=limit, event_types=event_types_list)
    history_data = [h.to_dict(include_relations=True) for h in history]

    return {
        "success": True,
        "data": {"item": item.to_dict(include_relations=True), "history": history_data, "total": len(history_data)},
    }


@router.get("/recent")
def get_recent_events(
    department_id: int | None = None,
    days: int = 7,
    limit: int = 50,
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj2.apps.helpdesk.services.inventory_history_service import InventoryHistoryService

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])

    dept_filter = department_id
    if "admin" not in user_roles and user_id not in secretary_comp_center:
        if "department_head" in user_roles:
            from itcj2.core.services.departments_service import get_user_department
            user_dept = get_user_department(db, user_id)
            if user_dept:
                dept_filter = user_dept.id
            else:
                return {"success": True, "data": [], "total": 0}
        else:
            raise HTTPException(403, detail={"success": False, "error": "No tiene permiso para ver eventos recientes"})

    events = InventoryHistoryService.get_recent_events(department_id=dept_filter, days=days, limit=limit)
    events_data = [e.to_dict(include_relations=True) for e in events]

    return {
        "success": True,
        "data": events_data,
        "total": len(events_data),
        "filters": {"department_id": dept_filter, "days": days, "limit": limit},
    }


@router.get("/user/{target_user_id}")
def get_user_assignment_history(
    target_user_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.all"]),
    db: DbSession = None,
):
    from itcj2.core.models.user import User
    from itcj2.apps.helpdesk.services.inventory_history_service import InventoryHistoryService

    target = db.get(User, target_user_id)
    if not target:
        raise HTTPException(404, detail={"success": False, "error": "Usuario no encontrado"})

    events = InventoryHistoryService.get_assignment_history(target_user_id)
    events_data = [e.to_dict(include_relations=True) for e in events]

    return {
        "success": True,
        "data": {
            "user": {"id": target.id, "full_name": target.full_name, "email": target.email},
            "history": events_data,
            "total": len(events_data),
        },
    }


@router.get("/maintenance/{item_id}")
def get_maintenance_history(
    item_id: int,
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj2.apps.helpdesk.models import InventoryItem
    from itcj2.apps.helpdesk.services.inventory_history_service import InventoryHistoryService

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])

    item = db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    if "admin" not in user_roles and user_id not in secretary_comp_center:
        if "department_head" in user_roles:
            from itcj2.core.services.departments_service import get_user_department
            user_dept = get_user_department(db, user_id)
            if not user_dept or item.department_id != user_dept.id:
                raise HTTPException(403, detail={"success": False, "error": "Sin permiso"})
        else:
            if item.assigned_to_user_id != user_id:
                raise HTTPException(403, detail={"success": False, "error": "Sin permiso"})

    maintenance_events = InventoryHistoryService.get_maintenance_history(item_id)
    events_data = [e.to_dict(include_relations=True) for e in maintenance_events]

    return {
        "success": True,
        "data": {"item": item.to_dict(include_relations=True), "maintenance_history": events_data, "total": len(events_data)},
    }


@router.get("/transfers")
def get_transfers(
    days: int = 30,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.all"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_history_service import InventoryHistoryService

    transfers = InventoryHistoryService.get_transfers_between_departments(days)
    transfers_data = [t.to_dict(include_relations=True) for t in transfers]

    return {"success": True, "data": transfers_data, "total": len(transfers_data), "filters": {"days": days}}
