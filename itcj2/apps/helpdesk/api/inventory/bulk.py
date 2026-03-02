"""
Inventory Bulk API v2 — 3 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/inventory/inventory_bulk.py
"""
import logging

from fastapi import APIRouter, HTTPException
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["helpdesk-inventory-bulk"])
logger = logging.getLogger(__name__)


@router.post("/validate-serials")
def validate_serial_numbers(
    body: dict,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.bulk.create"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_bulk_service import InventoryBulkService

    if not body.get("serial_numbers") or not isinstance(body["serial_numbers"], list):
        raise HTTPException(400, detail={"success": False, "error": "serial_numbers (array) requerido"})

    result = InventoryBulkService.validate_serial_numbers(body["serial_numbers"])
    return {"success": True, "validation": result}


@router.get("/next-inventory-number/{category_id}")
def get_next_inventory_number(
    category_id: int,
    year: int | None = None,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.bulk.create"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_bulk_service import InventoryBulkService

    try:
        inventory_number = InventoryBulkService.get_next_inventory_number(category_id, year)
        return {"success": True, "inventory_number": inventory_number}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        logger.error(f"Error al obtener siguiente número: {e}")
        raise HTTPException(500, detail={"success": False, "error": str(e)})


@router.post("/create", status_code=201)
def bulk_create_items(
    body: dict,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.bulk.create"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_bulk_service import InventoryBulkService

    user_id = int(user["sub"])

    if not body.get("category_id"):
        raise HTTPException(400, detail={"success": False, "error": "category_id requerido"})
    if not body.get("items") or not isinstance(body["items"], list):
        raise HTTPException(400, detail={"success": False, "error": "items (array) requerido"})
    if len(body["items"]) == 0:
        raise HTTPException(400, detail={"success": False, "error": "Debe incluir al menos un equipo"})

    serial_numbers = [item["serial_number"] for item in body["items"]]
    validation = InventoryBulkService.validate_serial_numbers(serial_numbers)

    if not validation["valid"]:
        raise HTTPException(400, detail={"success": False, "error": "Números de serie duplicados", "validation": validation})

    try:
        created_items = InventoryBulkService.bulk_create_items(body, user_id)
        return {
            "success": True,
            "message": f"{len(created_items)} equipos registrados exitosamente",
            "items": [item.to_dict(include_relations=True) for item in created_items],
        }
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        logger.error(f"Error en registro masivo: {e}")
        raise HTTPException(500, detail={"success": False, "error": str(e)})
