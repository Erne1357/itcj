"""
Inventory Stats API v2 — 8 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/inventory/inventory_stats.py
"""
from fastapi import APIRouter, HTTPException
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["helpdesk-inventory-stats"])


@router.get("/overview")
def get_overview(
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.stats"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_stats_service import InventoryStatsService
    stats = InventoryStatsService.get_overview_stats()
    return {"success": True, "data": stats}


@router.get("/by-category")
def get_by_category(
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.stats"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_stats_service import InventoryStatsService
    stats = InventoryStatsService.get_by_category()
    return {"success": True, "data": stats, "total": len(stats)}


@router.get("/by-department")
def get_by_department(
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.stats"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_stats_service import InventoryStatsService
    stats = InventoryStatsService.get_by_department()
    return {"success": True, "data": stats, "total": len(stats)}


@router.get("/problematic")
def get_problematic_items(
    min_tickets: int = 5,
    days: int = 180,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.stats"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_stats_service import InventoryStatsService

    problematic = InventoryStatsService.get_problematic_items(min_tickets=min_tickets, days=days)

    result = []
    for data in problematic:
        result.append({
            "item": data["item"].to_dict(include_relations=True),
            "ticket_count": data["ticket_count"],
            "mtbf_days": data["mtbf_days"],
            "recommendation": data["recommendation"],
        })

    return {"success": True, "data": result, "total": len(result), "filters": {"min_tickets": min_tickets, "days": days}}


@router.get("/warranty")
def get_warranty_report(
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.stats"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_stats_service import InventoryStatsService
    report = InventoryStatsService.get_warranty_report()
    return {"success": True, "data": report}


@router.get("/maintenance")
def get_maintenance_report(
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.stats"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_stats_service import InventoryStatsService
    report = InventoryStatsService.get_maintenance_report()
    return {"success": True, "data": report}


@router.get("/lifecycle")
def get_lifecycle_report(
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.stats"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_stats_service import InventoryStatsService
    report = InventoryStatsService.get_lifecycle_report()
    return {"success": True, "data": report}


@router.get("/department/{department_id}")
def get_department_stats(
    department_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.own_dept"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj2.apps.helpdesk.models import InventoryItem, InventoryCategory
    from sqlalchemy import func

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(["secretary_comp_center"])

    if "admin" not in user_roles and user_id not in secretary_comp_center and "tech_desarrollo" not in user_roles and "tech_soporte" not in user_roles:
        from itcj2.core.services.departments_service import get_user_department
        user_dept = get_user_department(user_id)
        if not user_dept or user_dept.id != department_id:
            raise HTTPException(403, detail={"success": False, "error": "No tiene permiso para ver este departamento"})

    total = InventoryItem.query.filter(InventoryItem.department_id == department_id, InventoryItem.is_active == True).count()

    by_status = db.query(
        InventoryItem.status, func.count(InventoryItem.id)
    ).filter(InventoryItem.department_id == department_id, InventoryItem.is_active == True).group_by(InventoryItem.status).all()
    status_counts = {status: count for status, count in by_status}

    assigned = InventoryItem.query.filter(
        InventoryItem.department_id == department_id, InventoryItem.is_active == True, InventoryItem.assigned_to_user_id.isnot(None),
    ).count()
    global_items = InventoryItem.query.filter(
        InventoryItem.department_id == department_id, InventoryItem.is_active == True, InventoryItem.assigned_to_user_id.is_(None),
    ).count()

    by_category = db.query(
        InventoryItem.category_id, func.count(InventoryItem.id)
    ).filter(InventoryItem.department_id == department_id, InventoryItem.is_active == True).group_by(InventoryItem.category_id).all()

    categories_data = []
    for cat_id, count in by_category:
        category = InventoryCategory.query.get(cat_id)
        if category:
            categories_data.append({"category_id": cat_id, "category_name": category.name, "count": count})

    return {
        "success": True,
        "data": {
            "department_id": department_id,
            "total": total,
            "by_status": status_counts,
            "assigned": assigned,
            "global": global_items,
            "by_category": categories_data,
        },
    }
