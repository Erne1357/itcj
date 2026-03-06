"""
Inventory Bulk Transfer API — Transferencia masiva entre departamentos.
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Body, HTTPException, Request
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["helpdesk-inventory-bulk-transfer"])
logger = logging.getLogger(__name__)


@router.post("/bulk-transfer")
def bulk_transfer_items(
    request: Request,
    body: dict = Body(...),
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.transfer"]),
    db: DbSession = None,
):
    """
    Transfiere múltiples equipos a otro departamento en una sola operación.

    Body:
      item_ids:             list[int]  — IDs de los equipos a transferir
      target_department_id: int        — Departamento destino
      notes:                str        — Motivo del traslado (opcional)
    """
    from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
    from itcj2.apps.helpdesk.models.inventory_history import InventoryHistory
    from itcj2.core.models.department import Department

    user_id = int(user["sub"])
    ip = request.client.host if request.client else None

    item_ids = body.get("item_ids", [])
    target_department_id = body.get("target_department_id")
    notes = body.get("notes", "").strip()

    if not item_ids or not isinstance(item_ids, list):
        raise HTTPException(400, detail={"success": False, "error": "item_ids (array) requerido"})
    if not target_department_id:
        raise HTTPException(400, detail={"success": False, "error": "target_department_id requerido"})

    target_dept = db.get(Department, int(target_department_id))
    if not target_dept:
        raise HTTPException(400, detail={"success": False, "error": "Departamento destino no encontrado"})

    transferred = []
    errors = []

    for item_id in item_ids:
        try:
            item = db.get(InventoryItem, int(item_id))
            if not item:
                errors.append({"item_id": item_id, "error": "No encontrado"})
                continue
            if not item.is_active:
                errors.append({"item_id": item_id, "inventory_number": item.inventory_number, "error": "Equipo dado de baja"})
                continue
            if item.department_id == target_department_id:
                errors.append({"item_id": item_id, "inventory_number": item.inventory_number, "error": "Ya pertenece al departamento destino"})
                continue

            old_dept = item.department
            old_dept_name = old_dept.name if old_dept else str(item.department_id)
            old_dept_id = item.department_id

            item.department_id = int(target_department_id)

            # Si el equipo está en un grupo del departamento origen, desvincularlo
            if item.group_id and item.group and item.group.department_id == old_dept_id:
                item.group_id = None

            history = InventoryHistory(
                item_id=item.id,
                event_type='TRANSFERRED',
                old_value={"department_id": old_dept_id, "department_name": old_dept_name},
                new_value={"department_id": int(target_department_id), "department_name": target_dept.name},
                notes=notes or f"Transferido a {target_dept.name}",
                performed_by_id=user_id,
                ip_address=ip,
            )
            db.add(history)
            transferred.append(item_id)

        except Exception as e:
            logger.error(f"bulk_transfer: error en item {item_id}: {e}")
            errors.append({"item_id": item_id, "error": str(e)})

    if transferred:
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"bulk_transfer: commit failed: {e}")
            raise HTTPException(500, detail={"success": False, "error": f"Error al guardar la transferencia: {str(e)}"})

    return {
        "success": True,
        "transferred_count": len(transferred),
        "transferred_ids": transferred,
        "errors": errors,
        "target_department": {"id": target_dept.id, "name": target_dept.name},
        "message": f"{len(transferred)} equipo(s) transferido(s) a {target_dept.name}" + (
            f". {len(errors)} error(es)." if errors else ""
        ),
    }


@router.post("/bulk-send-to-limbo")
def bulk_send_to_limbo(
    request: Request,
    body: dict = Body(...),
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.transfer"]),
    db: DbSession = None,
):
    """
    Envía múltiples equipos al 'limbo': sin usuario asignado ni departamento asignado.
    Quedan en estado pendiente de asignación (visibles en Equipos Pendientes).

    Body:
      item_ids: list[int] — IDs de los equipos
      notes:    str       — Motivo (opcional)
    """
    from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
    from itcj2.apps.helpdesk.models.inventory_history import InventoryHistory

    user_id = int(user["sub"])
    ip = request.client.host if request.client else None

    item_ids = body.get("item_ids", [])
    notes = body.get("notes", "").strip() or "Enviado al limbo (sin departamento / sin asignar)"

    if not item_ids or not isinstance(item_ids, list):
        raise HTTPException(400, detail={"success": False, "error": "item_ids (array) requerido"})

    sent = []
    errors = []

    for item_id in item_ids:
        try:
            item = db.get(InventoryItem, int(item_id))
            if not item:
                errors.append({"item_id": item_id, "error": "No encontrado"})
                continue
            if not item.is_active:
                errors.append({"item_id": item_id, "inventory_number": item.inventory_number, "error": "Equipo dado de baja"})
                continue

            old_dept_id = item.department_id
            old_user_id = item.assigned_to_user_id

            item.department_id = None
            item.assigned_to_user_id = None
            item.group_id = None

            history = InventoryHistory(
                item_id=item.id,
                event_type='TRANSFERRED',
                old_value={"department_id": old_dept_id, "assigned_to_user_id": old_user_id},
                new_value={"department_id": None, "assigned_to_user_id": None},
                notes=notes,
                performed_by_id=user_id,
                ip_address=ip,
            )
            db.add(history)
            sent.append(item_id)

        except Exception as e:
            logger.error(f"bulk_send_to_limbo: error en item {item_id}: {e}")
            errors.append({"item_id": item_id, "error": str(e)})

    if sent:
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"bulk_send_to_limbo: commit failed: {e}")
            raise HTTPException(500, detail={"success": False, "error": f"Error al guardar: {str(e)}"})

    return {
        "success": True,
        "sent_count": len(sent),
        "sent_ids": sent,
        "errors": errors,
        "message": f"{len(sent)} equipo(s) enviado(s) al limbo" + (
            f". {len(errors)} error(es)." if errors else ""
        ),
    }
