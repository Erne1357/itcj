"""
Inventory Dashboard API v2 — 5 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/inventory/inventory_dashboard.py
"""
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from itcj2.dependencies import DbSession, require_perms, require_app

router = APIRouter(tags=["helpdesk-inventory-dashboard"])


_STATS_SUBTREE = {"helpdesk.inventory.api.read.stats.subtree"}


@router.get("/widgets/quick-stats")
def get_quick_stats(
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import InventoryItem
    from itcj2.apps.helpdesk.utils.inventory_access import visible_department_ids

    user_id = int(user["sub"])
    visible = visible_department_ids(db, user, extra_subtree_perms=_STATS_SUBTREE)

    if visible is None:
        from itcj2.apps.helpdesk.services.inventory_stats_service import InventoryStatsService
        stats = InventoryStatsService.get_overview_stats(db)
        return {
            "success": True,
            "data": {
                "total_items": stats["total"],
                "active": stats["by_status"].get("ACTIVE", 0),
                "in_maintenance": stats["by_status"].get("MAINTENANCE", 0),
                "damaged": stats["by_status"].get("DAMAGED", 0),
                "assigned_to_users": stats["assigned_to_users"],
                "warranty_expiring_soon": stats["warranty_expiring_soon"],
                "needs_maintenance": stats["needs_maintenance"],
            },
        }

    if visible:
        # Scope departamental/subárbol (jefe de depto y/o .read.stats.subtree):
        # el mismo total que ve en la tabla de equipos, no solo su depto primario.
        total = db.query(InventoryItem).filter(InventoryItem.department_id.in_(visible), InventoryItem.is_active == True).count()
        active = db.query(InventoryItem).filter(InventoryItem.department_id.in_(visible), InventoryItem.is_active == True, InventoryItem.status == "ACTIVE").count()
        assigned = db.query(InventoryItem).filter(InventoryItem.department_id.in_(visible), InventoryItem.is_active == True, InventoryItem.assigned_to_user_id.isnot(None)).count()
        global_items = db.query(InventoryItem).filter(InventoryItem.department_id.in_(visible), InventoryItem.is_active == True, InventoryItem.assigned_to_user_id.is_(None)).count()

        return {
            "success": True,
            "data": {"total_items": total, "active": active, "assigned_to_users": assigned, "global": global_items},
        }

    # Sin scope departamental/subárbol resuelto (puesto vencido o ninguno):
    # fallback histórico — solo lo que tiene asignado.
    my_items = db.query(InventoryItem).filter(InventoryItem.assigned_to_user_id == user_id, InventoryItem.is_active == True).count()
    return {"success": True, "data": {"my_items": my_items}}


@router.get("/widgets/alerts")
def get_alerts(
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.stats"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import InventoryItem, Ticket, TicketInventoryItem
    from sqlalchemy import func

    alerts = []

    warranty_expiring = db.query(InventoryItem).filter(
        InventoryItem.is_active == True,
        InventoryItem.warranty_expiration >= date.today(),
        InventoryItem.warranty_expiration <= date.today() + timedelta(days=30),
    ).count()
    if warranty_expiring > 0:
        alerts.append({
            "type": "warning", "icon": "fas fa-shield-alt", "title": "Garantías por vencer",
            "message": f"{warranty_expiring} equipo(s) con garantía venciendo en 30 días",
            "action": "/inventory/stats/warranty", "priority": "medium",
        })

    maintenance_overdue = db.query(InventoryItem).filter(
        InventoryItem.is_active == True,
        InventoryItem.next_maintenance_date.isnot(None),
        InventoryItem.next_maintenance_date < date.today(),
    ).count()
    if maintenance_overdue > 0:
        alerts.append({
            "type": "danger", "icon": "fas fa-tools", "title": "Mantenimiento vencido",
            "message": f"{maintenance_overdue} equipo(s) requieren mantenimiento",
            "action": "/inventory/stats/maintenance", "priority": "high",
        })

    damaged = db.query(InventoryItem).filter(InventoryItem.is_active == True, InventoryItem.status == "DAMAGED").count()
    if damaged > 0:
        alerts.append({
            "type": "danger", "icon": "fas fa-exclamation-triangle", "title": "Equipos dañados",
            "message": f"{damaged} equipo(s) en estado dañado",
            "action": "/inventory/items?status=DAMAGED", "priority": "high",
        })

    six_months_ago = date.today() - timedelta(days=180)
    problematic = db.query(InventoryItem.id).join(
        TicketInventoryItem, TicketInventoryItem.inventory_item_id == InventoryItem.id
    ).join(
        Ticket, Ticket.id == TicketInventoryItem.ticket_id
    ).filter(
        InventoryItem.is_active == True, Ticket.created_at >= six_months_ago
    ).group_by(InventoryItem.id).having(func.count(Ticket.id) >= 10).count()

    if problematic > 0:
        alerts.append({
            "type": "warning", "icon": "fas fa-chart-line", "title": "Equipos problemáticos",
            "message": f"{problematic} equipo(s) con múltiples fallas",
            "action": "/inventory/stats/problematic", "priority": "medium",
        })

    priority_order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda x: priority_order.get(x["priority"], 3))

    return {"success": True, "data": alerts, "total": len(alerts)}


@router.get("/widgets/recent-activity")
def get_recent_activity(
    limit: int = 10,
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    from datetime import datetime, timedelta

    from sqlalchemy import desc

    from itcj2.apps.helpdesk.models import InventoryHistory, InventoryItem
    from itcj2.apps.helpdesk.utils.inventory_access import visible_department_ids

    visible = visible_department_ids(db, user, extra_subtree_perms=_STATS_SUBTREE)

    # Réplica de InventoryHistoryService.get_recent_events, pero con `.in_()` para
    # soportar un CONJUNTO de departamentos (subárbol) — el service solo filtra
    # por `==` un department_id escalar (fuera del alcance de este fix).
    since_date = datetime.now() - timedelta(days=7)
    query = db.query(InventoryHistory).join(
        InventoryItem, InventoryHistory.item_id == InventoryItem.id
    ).filter(InventoryHistory.timestamp >= since_date)
    if visible is not None:
        query = query.filter(InventoryItem.department_id.in_(visible or {-1}))
    events = query.order_by(desc(InventoryHistory.timestamp)).limit(limit).all()

    events_data = []
    for event in events:
        events_data.append({
            "id": event.id,
            "event_type": event.event_type,
            "event_description": event.get_event_description(event.event_type),
            "item": {
                "id": event.item.id, "inventory_number": event.item.inventory_number, "display_name": event.item.display_name,
            } if event.item else None,
            "performed_by": {
                "id": event.performed_by.id, "full_name": event.performed_by.full_name,
            } if event.performed_by else None,
            "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            "notes": event.notes,
        })

    return {"success": True, "data": events_data, "total": len(events_data)}


@router.get("/widgets/category-chart")
def get_category_chart(
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_stats_service import InventoryStatsService
    from itcj2.apps.helpdesk.models import InventoryItem, InventoryCategory
    from sqlalchemy import func, and_
    from itcj2.apps.helpdesk.utils.inventory_access import visible_department_ids

    visible = visible_department_ids(db, user, extra_subtree_perms=_STATS_SUBTREE)

    if visible is None:
        stats = InventoryStatsService.get_by_category(db)
    elif visible:
        results = db.query(
            InventoryCategory.name, func.count(InventoryItem.id)
        ).outerjoin(
            InventoryItem,
            and_(
                InventoryItem.category_id == InventoryCategory.id,
                InventoryItem.department_id.in_(visible),
                InventoryItem.is_active == True,
            ),
        ).filter(InventoryCategory.is_active == True).group_by(InventoryCategory.name).all()

        stats = [{"category_name": name, "count": count} for name, count in results if count > 0]
    else:
        return {"success": True, "data": {"labels": [], "datasets": []}}

    labels = [s["category_name"] for s in stats]
    data = [s["count"] for s in stats]

    return {
        "success": True,
        "data": {
            "labels": labels,
            "datasets": [{
                "label": "Equipos",
                "data": data,
                "backgroundColor": ["#4e73df", "#1cc88a", "#36b9cc", "#f6c23e", "#e74a3b", "#858796", "#5a5c69", "#2e59d9"],
            }],
        },
    }


@router.get("/widgets/status-chart")
def get_status_chart(
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import InventoryItem
    from sqlalchemy import func
    from itcj2.apps.helpdesk.utils.inventory_access import visible_department_ids

    visible = visible_department_ids(db, user, extra_subtree_perms=_STATS_SUBTREE)

    results_query = db.query(
        InventoryItem.status, func.count(InventoryItem.id)
    ).filter(InventoryItem.is_active == True)

    # Fail-closed: sin scope resuelto (puesto vencido o ninguno), NO se debe caer
    # al conteo global del instituto — antes `if user_dept:` dejaba la query sin
    # filtrar cuando no había departamento resuelto.
    if visible is not None:
        results_query = results_query.filter(InventoryItem.department_id.in_(visible or {-1}))

    results = results_query.group_by(InventoryItem.status).all()

    status_labels = {"ACTIVE": "Activo", "MAINTENANCE": "Mantenimiento", "DAMAGED": "Dañado", "LOST": "Extraviado"}
    status_colors = {"ACTIVE": "#1cc88a", "MAINTENANCE": "#f6c23e", "DAMAGED": "#e74a3b", "LOST": "#858796"}

    labels = [status_labels.get(status, status) for status, _ in results]
    data = [count for _, count in results]
    colors = [status_colors.get(status, "#858796") for status, _ in results]

    return {
        "success": True,
        "data": {
            "labels": labels,
            "datasets": [{"data": data, "backgroundColor": colors}],
        },
    }
