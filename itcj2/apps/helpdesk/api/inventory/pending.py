"""
Inventory Pending API v2 — 3 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/inventory/inventory_pending.py
"""
import logging

from fastapi import APIRouter, HTTPException
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["helpdesk-inventory-pending"])
logger = logging.getLogger(__name__)


@router.get("")
def get_pending_items(
    category_id: int | None = None,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.pending"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_pending_service import InventoryPendingService

    items = InventoryPendingService.get_pending_items(category_id)
    return {"success": True, "data": [item.to_dict(include_relations=True) for item in items]}


@router.get("/stats")
def get_pending_stats(
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.pending"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_pending_service import InventoryPendingService

    stats = InventoryPendingService.get_pending_stats()
    return {"success": True, "stats": stats}


@router.post("/assign-to-department")
def assign_to_department(
    body: dict,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.assign.pending"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_pending_service import InventoryPendingService

    user_id = int(user["sub"])

    if not body.get("item_ids") or not isinstance(body["item_ids"], list):
        raise HTTPException(400, detail={"success": False, "error": "item_ids (array) requerido"})
    if not body.get("department_id"):
        raise HTTPException(400, detail={"success": False, "error": "department_id requerido"})

    try:
        assigned_items = InventoryPendingService.assign_to_department(
            body["item_ids"], body["department_id"], user_id,
            body.get("location_detail"), body.get("notes"),
        )
        return {
            "success": True,
            "message": f"{len(assigned_items)} equipos asignados exitosamente",
            "items": [item.to_dict(include_relations=True) for item in assigned_items],
        }
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        logger.error(f"Error al asignar equipos pendientes: {e}")
        raise HTTPException(500, detail={"success": False, "error": str(e)})
