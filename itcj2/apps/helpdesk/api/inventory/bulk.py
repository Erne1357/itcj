"""
Inventory Bulk API v2 — Registro masivo con listas de seriales.
"""
import logging

from fastapi import APIRouter, HTTPException
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["helpdesk-inventory-bulk"])
logger = logging.getLogger(__name__)


@router.post("/validate-serials")
def validate_bulk_serials(
    body: dict,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.bulk.create"]),
    db: DbSession = None,
):
    """
    Valida las listas de seriales antes del registro masivo.
    Verifica duplicados en la lista y en la BD para los 3 campos de identificación.

    Body: { supplier_serial_list, itcj_serial_list, id_tecnm_list, serial_separator }
    """
    from itcj2.apps.helpdesk.services.inventory_bulk_service import InventoryBulkService

    result = InventoryBulkService.validate_bulk_serials(db, body)
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
        inventory_number = InventoryBulkService.get_next_inventory_number(db, category_id, year)
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
    """
    Registro masivo de equipos.

    Body:
      category_id          (requerido)
      brand, model, specifications, acquisition_date, warranty_expiration,
      maintenance_frequency_days, notes, department_id  (comunes a todos)
      quantity             (int) — número de equipos, alternativa a 'items'
      items                (list[dict]) — overrides por posición (department_id, location_detail, etc.)
      supplier_serial_list (str) — seriales de proveedor separados por serial_separator
      itcj_serial_list     (str) — seriales ITCJ
      id_tecnm_list        (str) — IDs TecNM
      serial_separator     ("comma"|"semicolon"|"space"|"newline"|"auto")
    """
    from itcj2.apps.helpdesk.services.inventory_bulk_service import InventoryBulkService

    user_id = int(user["sub"])

    if not body.get("category_id"):
        raise HTTPException(400, detail={"success": False, "error": "category_id requerido"})

    has_items = body.get("items") and len(body["items"]) > 0
    has_quantity = body.get("quantity") and int(body["quantity"]) > 0
    if not has_items and not has_quantity:
        raise HTTPException(400, detail={
            "success": False,
            "error": "Se requiere 'items' (array) o 'quantity' (entero > 0)",
        })

    has_serial_lists = any([
        body.get("supplier_serial_list"),
        body.get("itcj_serial_list"),
        body.get("id_tecnm_list"),
    ])
    if has_serial_lists:
        validation = InventoryBulkService.validate_bulk_serials(db, body)
        if not validation["valid"]:
            raise HTTPException(400, detail={
                "success": False,
                "error": "Errores en las listas de seriales",
                "validation": validation,
            })

    try:
        created_items = InventoryBulkService.bulk_create_items(db, body, user_id)
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
