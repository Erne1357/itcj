"""
Inventory Assignments API v2 — 5 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/inventory/inventory_assignments.py
"""
from fastapi import APIRouter, HTTPException, Request
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["helpdesk-inventory-assignments"])


@router.post("/assign")
def assign_to_user(
    body: dict,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.assign"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj2.apps.helpdesk.models import InventoryItem
    from itcj2.apps.helpdesk.services.inventory_service import InventoryService
    from itcj2.apps.helpdesk.utils.inventory_validators import InventoryValidators

    from itcj2.apps.helpdesk.utils.inventory_access import is_comp_center_user

    assigned_by_id = int(user["sub"])
    user_roles = user_roles_in_app(db, assigned_by_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])
    is_comp_center = is_comp_center_user(db, assigned_by_id)

    if not body.get("item_id"):
        raise HTTPException(400, detail={"success": False, "error": "ID del equipo requerido"})
    if not body.get("user_id"):
        raise HTTPException(400, detail={"success": False, "error": "ID del usuario requerido"})

    item = db.get(InventoryItem, body["item_id"])
    if not item or not item.is_active:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    if "admin" not in user_roles and assigned_by_id not in secretary_comp_center and not is_comp_center:
        from itcj2.core.services.departments_service import get_user_department
        user_dept = get_user_department(db, assigned_by_id)
        if not user_dept or user_dept.id != item.department_id:
            raise HTTPException(403, detail={"success": False, "error": "No tiene permiso para asignar equipos de este departamento"})

    is_valid, message, target_user = InventoryValidators.validate_user_for_assignment(body["user_id"], item.department_id)
    if not is_valid:
        raise HTTPException(400, detail={"success": False, "error": message})

    try:
        updated_item = InventoryService.assign_to_user(
            db,
            item_id=body["item_id"], user_id=body["user_id"], assigned_by_id=assigned_by_id,
            location=body.get("location"), notes=body.get("notes"),
            ip_address=request.client.host if request.client else None,
        )
        return {"success": True, "message": f"Equipo asignado a {target_user.full_name}", "data": updated_item.to_dict(include_relations=True)}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail={"success": False, "error": f"Error: {str(e)}"})


@router.post("/unassign")
def unassign_from_user(
    body: dict,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.unassign"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj2.apps.helpdesk.models import InventoryItem
    from itcj2.apps.helpdesk.services.inventory_service import InventoryService

    from itcj2.apps.helpdesk.utils.inventory_access import is_comp_center_user

    unassigned_by_id = int(user["sub"])
    user_roles = user_roles_in_app(db, unassigned_by_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])
    is_comp_center = is_comp_center_user(db, unassigned_by_id)

    if not body.get("item_id"):
        raise HTTPException(400, detail={"success": False, "error": "ID del equipo requerido"})

    item = db.get(InventoryItem, body["item_id"])
    if not item or not item.is_active:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    if not item.is_assigned_to_user:
        raise HTTPException(400, detail={"success": False, "error": "El equipo no está asignado a ningún usuario"})

    if "admin" not in user_roles and unassigned_by_id not in secretary_comp_center and not is_comp_center:
        from itcj2.core.services.departments_service import get_user_department
        user_dept = get_user_department(db, unassigned_by_id)
        if not user_dept or user_dept.id != item.department_id:
            raise HTTPException(403, detail={"success": False, "error": "No tiene permiso para liberar equipos de este departamento"})

    try:
        updated_item = InventoryService.unassign_from_user(
            db,
            item_id=body["item_id"], unassigned_by_id=unassigned_by_id,
            notes=body.get("notes"),
            ip_address=request.client.host if request.client else None,
        )
        return {"success": True, "message": "Equipo liberado exitosamente", "data": updated_item.to_dict(include_relations=True)}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail={"success": False, "error": f"Error: {str(e)}"})


@router.post("/transfer")
def transfer_between_departments(
    body: dict,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.transfer"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import InventoryItem
    from itcj2.apps.helpdesk.utils.inventory_validators import InventoryValidators
    from itcj2.apps.helpdesk.services import InventoryHistoryService

    user_id = int(user["sub"])

    if not body.get("item_id"):
        raise HTTPException(400, detail={"success": False, "error": "ID del equipo requerido"})
    if not body.get("new_department_id"):
        raise HTTPException(400, detail={"success": False, "error": "Departamento destino requerido"})
    if not body.get("notes") or len(body["notes"].strip()) < 10:
        raise HTTPException(400, detail={"success": False, "error": "Debe especificar la razón de la transferencia (mínimo 10 caracteres)"})

    item = db.get(InventoryItem, body["item_id"])
    if not item or not item.is_active:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    is_valid, message, new_dept = InventoryValidators.validate_department(body["new_department_id"])
    if not is_valid:
        raise HTTPException(400, detail={"success": False, "error": message})

    if item.department_id == new_dept.id:
        raise HTTPException(400, detail={"success": False, "error": "El equipo ya pertenece a ese departamento"})

    if item.active_tickets_count > 0:
        raise HTTPException(400, detail={"success": False, "error": f"No se puede transferir: tiene {item.active_tickets_count} ticket(s) activo(s)"})

    try:
        old_dept_name = item.department.name if item.department else None
        old_user = item.assigned_to_user.full_name if item.assigned_to_user else None

        if item.assigned_to_user_id:
            item.assigned_to_user_id = None
            item.assigned_by_id = None
            item.assigned_at = None

        item.department_id = new_dept.id

        InventoryHistoryService.log_event(
            db,
            item_id=item.id, event_type="TRANSFERRED", performed_by_id=user_id,
            old_value={"department_id": item.department_id, "department_name": old_dept_name, "assigned_to_user": old_user},
            new_value={"department_id": new_dept.id, "department_name": new_dept.name, "assigned_to_user": None},
            notes=body["notes"],
            ip_address=request.client.host if request.client else None,
        )
        db.commit()

        return {"success": True, "message": f"Equipo transferido a {new_dept.name}", "data": item.to_dict(include_relations=True)}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail={"success": False, "error": f"Error: {str(e)}"})


@router.post("/bulk-assign")
def bulk_assign(
    body: dict,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.assign"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import InventoryItem
    from itcj2.apps.helpdesk.services.inventory_service import InventoryService

    assigned_by_id = int(user["sub"])

    if not body.get("item_ids") or not isinstance(body["item_ids"], list):
        raise HTTPException(400, detail={"success": False, "error": "Lista de IDs requerida"})
    if not body.get("user_id"):
        raise HTTPException(400, detail={"success": False, "error": "Usuario destino requerido"})

    results = {"success": [], "failed": []}

    for item_id in body["item_ids"]:
        try:
            item = db.get(InventoryItem, item_id)
            if not item or not item.is_active:
                results["failed"].append({"item_id": item_id, "error": "Equipo no encontrado"})
                continue
            InventoryService.assign_to_user(
                db,
                item_id=item_id, user_id=body["user_id"], assigned_by_id=assigned_by_id,
                notes=body.get("notes"),
                ip_address=request.client.host if request.client else None,
            )
            results["success"].append({"item_id": item_id, "inventory_number": item.inventory_number})
        except Exception as e:
            results["failed"].append({"item_id": item_id, "error": str(e)})

    status_code = 200 if not results["failed"] else 207
    # FastAPI doesn't support dynamic status codes easily, but we return the data
    return {
        "success": len(results["failed"]) == 0,
        "message": f"Asignados: {len(results['success'])}, Fallidos: {len(results['failed'])}",
        "data": results,
    }


@router.post("/update-location")
def update_location(
    body: dict,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.update.location"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj2.apps.helpdesk.models import InventoryItem
    from itcj2.apps.helpdesk.services import InventoryHistoryService

    from itcj2.apps.helpdesk.utils.inventory_access import is_comp_center_user

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])
    is_comp_center = is_comp_center_user(db, user_id)

    if not body.get("item_id"):
        raise HTTPException(400, detail={"success": False, "error": "ID del equipo requerido"})
    if not body.get("location"):
        raise HTTPException(400, detail={"success": False, "error": "Ubicación requerida"})

    item = db.get(InventoryItem, body["item_id"])
    if not item or not item.is_active:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    if "admin" not in user_roles and user_id not in secretary_comp_center and "tech_desarrollo" not in user_roles and "tech_soporte" not in user_roles and not is_comp_center:
        from itcj2.core.services.departments_service import get_user_department
        user_dept = get_user_department(db, user_id)
        if not user_dept or user_dept.id != item.department_id:
            raise HTTPException(403, detail={"success": False, "error": "No tiene permiso para actualizar equipos de este departamento"})

    try:
        old_location = item.location_detail
        item.location_detail = body["location"]

        InventoryHistoryService.log_event(
            db,
            item_id=item.id, event_type="LOCATION_CHANGED", performed_by_id=user_id,
            old_value={"location": old_location},
            new_value={"location": body["location"]},
            notes=body.get("notes", "Ubicación actualizada"),
            ip_address=request.client.host if request.client else None,
        )
        db.commit()

        return {"success": True, "message": "Ubicación actualizada", "data": item.to_dict(include_relations=True)}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail={"success": False, "error": f"Error: {str(e)}"})
