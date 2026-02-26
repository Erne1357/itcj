"""
Inventory Groups API v2 — 11 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/inventory/inventory_groups.py
"""
import logging

from fastapi import APIRouter, HTTPException
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["helpdesk-inventory-groups"])
logger = logging.getLogger(__name__)


@router.get("")
def get_all_groups(
    include_inactive: str = "false",
    department_id: int | None = None,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory_groups.api.read.all"]),
    db: DbSession = None,
):
    from itcj.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj.apps.helpdesk.models import InventoryGroup

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(["secretary_comp_center"])

    if "admin" not in user_roles and user_id not in secretary_comp_center and "tech_desarrollo" not in user_roles and "tech_soporte" not in user_roles:
        raise HTTPException(403, detail={"success": False, "error": "No tiene permisos para ver todos los grupos"})

    query = InventoryGroup.query
    if include_inactive.lower() != "true":
        query = query.filter_by(is_active=True)
    if department_id is not None:
        query = query.filter_by(department_id=department_id)

    groups = query.order_by(InventoryGroup.name).all()
    return {"success": True, "data": [g.to_dict(include_capacities=True) for g in groups]}


@router.get("/department/{department_id}")
def get_groups_by_department(
    department_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory_groups.api.read.own_dept"]),
    db: DbSession = None,
):
    from itcj.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj.apps.helpdesk.services.inventory_group_service import InventoryGroupService

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(["secretary_comp_center"])

    if "admin" not in user_roles and user_id not in secretary_comp_center and "tech_desarrollo" not in user_roles and "tech_soporte" not in user_roles:
        from itcj.core.services.departments_service import get_user_department
        user_dept = get_user_department(user_id)
        if not user_dept or user_dept.id != department_id:
            raise HTTPException(403, detail={"success": False, "error": "No tiene permisos para ver grupos de este departamento"})

    groups = InventoryGroupService.get_groups_by_department(department_id)
    return {"success": True, "data": [g.to_dict(include_capacities=True) for g in groups]}


@router.get("/{group_id}")
def get_group_detail(
    group_id: int,
    include_items: str = "false",
    user: dict = require_perms("helpdesk", ["helpdesk.inventory_groups.api.read.own_dept"]),
    db: DbSession = None,
):
    from itcj.apps.helpdesk.models import InventoryGroup

    group = InventoryGroup.query.get(group_id)
    if not group:
        raise HTTPException(404, detail={"success": False, "error": "Grupo no encontrado"})

    return {"success": True, "data": group.to_dict(include_items=include_items.lower() == "true", include_capacities=True)}


@router.get("/{group_id}/items")
def get_group_items(
    group_id: int,
    category_id: int | None = None,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory_groups.api.read.own_dept"]),
    db: DbSession = None,
):
    from itcj.apps.helpdesk.services.inventory_group_service import InventoryGroupService

    items = InventoryGroupService.get_group_items(group_id, category_id)
    return {"success": True, "data": [item.to_dict(include_relations=True) for item in items]}


@router.post("", status_code=201)
def create_group(
    body: dict,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory_groups.api.create"]),
    db: DbSession = None,
):
    from itcj.apps.helpdesk.services.inventory_group_service import InventoryGroupService

    user_id = int(user["sub"])

    if not body.get("name"):
        raise HTTPException(400, detail={"success": False, "error": "Nombre requerido"})
    if not body.get("department_id"):
        raise HTTPException(400, detail={"success": False, "error": "Departamento requerido"})

    try:
        group = InventoryGroupService.create_group(body, user_id)
        return {"success": True, "message": "Grupo creado exitosamente", "data": group.to_dict(include_capacities=True)}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        logger.error(f"Error al crear grupo: {e}")
        raise HTTPException(500, detail={"success": False, "error": str(e)})


@router.put("/{group_id}")
def update_group(
    group_id: int,
    body: dict,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory_groups.api.update"]),
    db: DbSession = None,
):
    from itcj.apps.helpdesk.services.inventory_group_service import InventoryGroupService

    try:
        group = InventoryGroupService.update_group(group_id, body)
        return {"success": True, "message": "Grupo actualizado exitosamente", "data": group.to_dict(include_capacities=True)}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        logger.error(f"Error al actualizar grupo: {e}")
        raise HTTPException(500, detail={"success": False, "error": str(e)})


@router.put("/{group_id}/capacities")
def update_capacities(
    group_id: int,
    body: dict,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory_groups.api.update.capacity"]),
    db: DbSession = None,
):
    from itcj.apps.helpdesk.services.inventory_group_service import InventoryGroupService

    if "capacities" not in body:
        raise HTTPException(400, detail={"success": False, "error": "Capacidades requeridas"})

    try:
        group = InventoryGroupService.update_capacities(group_id, body["capacities"])
        return {"success": True, "message": "Capacidades actualizadas exitosamente", "data": group.to_dict(include_capacities=True)}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        logger.error(f"Error al actualizar capacidades: {e}")
        raise HTTPException(500, detail={"success": False, "error": str(e)})


@router.delete("/{group_id}")
def delete_group(
    group_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory_groups.api.delete"]),
    db: DbSession = None,
):
    from itcj.apps.helpdesk.services.inventory_group_service import InventoryGroupService

    try:
        InventoryGroupService.delete_group(group_id)
        return {"success": True, "message": "Grupo eliminado exitosamente"}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        logger.error(f"Error al eliminar grupo: {e}")
        raise HTTPException(500, detail={"success": False, "error": str(e)})


@router.post("/{group_id}/assign-item")
def assign_item_to_group(
    group_id: int,
    body: dict,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory_groups.api.assign.items"]),
    db: DbSession = None,
):
    from itcj.apps.helpdesk.services.inventory_group_service import InventoryGroupService

    user_id = int(user["sub"])
    if not body.get("item_id"):
        raise HTTPException(400, detail={"success": False, "error": "item_id requerido"})

    try:
        item = InventoryGroupService.assign_item_to_group(body["item_id"], group_id, user_id)
        return {"success": True, "message": "Equipo asignado al grupo exitosamente", "data": item.to_dict(include_relations=True)}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        logger.error(f"Error al asignar equipo a grupo: {e}")
        raise HTTPException(500, detail={"success": False, "error": str(e)})


@router.post("/unassign-item/{item_id}")
def unassign_item_from_group(
    item_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory_groups.api.assign.items"]),
    db: DbSession = None,
):
    from itcj.apps.helpdesk.services.inventory_group_service import InventoryGroupService

    user_id = int(user["sub"])

    try:
        item = InventoryGroupService.unassign_item_from_group(item_id, user_id)
        return {"success": True, "message": "Equipo removido del grupo exitosamente", "data": item.to_dict(include_relations=True)}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        logger.error(f"Error al desasignar equipo de grupo: {e}")
        raise HTTPException(500, detail={"success": False, "error": str(e)})


@router.post("/{group_id}/bulk-assign")
def bulk_assign_items_to_group(
    group_id: int,
    body: dict,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory_groups.api.assign.items"]),
    db: DbSession = None,
):
    from itcj.apps.helpdesk.services.inventory_group_service import InventoryGroupService

    user_id = int(user["sub"])

    if not body.get("item_ids") or not isinstance(body["item_ids"], list):
        raise HTTPException(400, detail={"success": False, "error": "item_ids (array) requerido"})

    assigned = []
    errors = []

    for item_id in body["item_ids"]:
        try:
            item = InventoryGroupService.assign_item_to_group(item_id, group_id, user_id)
            assigned.append(item.to_dict())
        except Exception as e:
            errors.append({"item_id": item_id, "error": str(e)})

    return {
        "success": len(errors) == 0,
        "message": f"{len(assigned)} equipos asignados, {len(errors)} errores",
        "assigned": assigned,
        "errors": errors,
    }
