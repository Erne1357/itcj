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
    from itcj2.apps.helpdesk.models import InventoryItem
    from itcj2.apps.helpdesk.services.inventory_history_service import InventoryHistoryService
    from itcj2.apps.helpdesk.utils.inventory_access import visible_department_ids

    user_id = int(user["sub"])

    item = db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    # Mismo criterio que items.py::get_item: acceso completo (admin/técnicos/CC/
    # .read.all) = None, o dentro del scope departamental/subárbol, o asignado.
    visible = visible_department_ids(db, user)
    if visible is not None:
        if item.department_id not in visible and item.assigned_to_user_id != user_id:
            raise HTTPException(403, detail={"success": False, "error": "No tiene permiso para ver el historial de este equipo"})

    event_types_list = event_types.split(",") if event_types else None
    history = InventoryHistoryService.get_item_history(db, item_id=item_id, limit=limit, event_types=event_types_list)
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
    from datetime import datetime, timedelta

    from sqlalchemy import desc

    from itcj2.apps.helpdesk.models import InventoryHistory, InventoryItem
    from itcj2.apps.helpdesk.utils.inventory_access import visible_department_ids

    # Antes: la lista de excepciones (admin/secretaría CC/CC) omitía
    # tech_desarrollo/tech_soporte (acceso completo por rol), así que un técnico
    # caía al `else` y recibía 403. `visible_department_ids` ya cubre las 3 vías
    # de acceso completo (roles, posición de secretaría, permisos .read.all) sin
    # tener que enumerarlas a mano aquí.
    visible = visible_department_ids(db, user)

    # Réplica de InventoryHistoryService.get_recent_events, pero con `.in_()`
    # para soportar un CONJUNTO de departamentos (subárbol) — el service solo
    # filtra por `==` un department_id escalar (fuera del alcance de este fix).
    since_date = datetime.now() - timedelta(days=days)
    query = db.query(InventoryHistory).join(
        InventoryItem, InventoryHistory.item_id == InventoryItem.id
    ).filter(InventoryHistory.timestamp >= since_date)

    if visible is None:
        # Ve todo: el ?department_id= se honra tal cual (comportamiento previo
        # de admin/secretaría CC/técnicos).
        if department_id:
            query = query.filter(InventoryItem.department_id == department_id)
    elif department_id:
        wanted = visible & {department_id}
        query = query.filter(InventoryItem.department_id.in_(wanted or {-1}))
    else:
        # Fail-closed: sin scope (o "puesto vencido" sin departamento resuelto),
        # vacío — nunca los eventos de toda la institución.
        query = query.filter(InventoryItem.department_id.in_(visible or {-1}))

    events = query.order_by(desc(InventoryHistory.timestamp)).limit(limit).all()
    events_data = [e.to_dict(include_relations=True) for e in events]

    return {
        "success": True,
        "data": events_data,
        "total": len(events_data),
        "filters": {"department_id": department_id, "days": days, "limit": limit},
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

    events = InventoryHistoryService.get_assignment_history(db, target_user_id)
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
    from itcj2.apps.helpdesk.models import InventoryItem
    from itcj2.apps.helpdesk.services.inventory_history_service import InventoryHistoryService
    from itcj2.apps.helpdesk.utils.inventory_access import visible_department_ids

    user_id = int(user["sub"])

    item = db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    visible = visible_department_ids(db, user)
    if visible is not None:
        if item.department_id not in visible and item.assigned_to_user_id != user_id:
            raise HTTPException(403, detail={"success": False, "error": "Sin permiso"})

    maintenance_events = InventoryHistoryService.get_maintenance_history(db, item_id)
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

    transfers = InventoryHistoryService.get_transfers_between_departments(db, days)
    transfers_data = [t.to_dict(include_relations=True) for t in transfers]

    return {"success": True, "data": transfers_data, "total": len(transfers_data), "filters": {"days": days}}
