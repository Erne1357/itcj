"""
Inventory Items API v2 — 10 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/inventory/inventory_items.py
"""
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from itcj2.dependencies import DbSession, require_perms, require_app

router = APIRouter(tags=["helpdesk-inventory-items"])
logger = logging.getLogger(__name__)


@router.get("")
def get_items(
    request: Request,
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj2.apps.helpdesk.models import InventoryItem
    from sqlalchemy import or_

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])
    user_dept = None
    params = request.query_params

    query = db.query(InventoryItem).filter_by(is_active=True)

    if "admin" not in user_roles and user_id not in secretary_comp_center and "tech_desarrollo" not in user_roles and "tech_soporte" not in user_roles:
        if "department_head" in user_roles:
            from itcj2.core.services.departments_service import get_user_department
            user_dept = get_user_department(db, user_id)
            if user_dept:
                query = query.filter(InventoryItem.department_id == user_dept.id)
            else:
                return {"success": True, "data": [], "total": 0, "page": 1, "per_page": 50, "total_pages": 0}
        else:
            department_id = params.get("department_id")
            if department_id:
                query = query.filter(InventoryItem.department_id == int(department_id))
            else:
                query = query.filter(InventoryItem.assigned_to_user_id == user_id)

    category_id = params.get("category_id")
    if category_id:
        query = query.filter(InventoryItem.category_id == int(category_id))

    if user_dept is None:
        department_id = params.get("department_id")
        if department_id:
            query = query.filter(InventoryItem.department_id == int(department_id))

    status = params.get("status")
    if status:
        query = query.filter(InventoryItem.status == status.upper())

    assigned = params.get("assigned")
    if assigned:
        if assigned.lower() == "yes":
            query = query.filter(InventoryItem.assigned_to_user_id.isnot(None))
        elif assigned.lower() == "no":
            query = query.filter(InventoryItem.assigned_to_user_id.is_(None))

    search = params.get("search")
    if search:
        search_term = f"%{search}%"
        query = query.filter(or_(
            InventoryItem.inventory_number.ilike(search_term),
            InventoryItem.brand.ilike(search_term),
            InventoryItem.model.ilike(search_term),
            InventoryItem.serial_number.ilike(search_term),
        ))

    page = int(params.get("page", "1"))
    per_page = min(int(params.get("per_page", "50")), 100)

    from itcj2.models.base import paginate
    paginated = paginate(query, page=page, per_page=per_page)
    items = [item.to_dict(include_relations=True) for item in paginated.items]

    return {
        "success": True,
        "data": items,
        "total": paginated.total,
        "page": page,
        "per_page": per_page,
        "total_pages": paginated.pages,
    }


@router.get("/my-equipment")
def get_my_equipment(
    category_id: int | None = None,
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_service import InventoryService

    user_id = int(user["sub"])
    items = InventoryService.get_items_for_user(user_id, category_id)
    return {"success": True, "data": [item.to_dict(include_relations=True) for item in items], "total": len(items)}


@router.get("/user/{target_user_id}/equipment")
def get_user_equipment(
    target_user_id: int,
    category_id: int | None = None,
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj2.apps.helpdesk.services.inventory_service import InventoryService

    current_user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, current_user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])

    if "admin" not in user_roles and current_user_id not in secretary_comp_center and "tech_desarrollo" not in user_roles and "tech_soporte" not in user_roles:
        raise HTTPException(403, detail={"success": False, "error": "No tiene permiso para consultar equipos de otros usuarios"})

    items = InventoryService.get_items_for_user(target_user_id, category_id)
    return {"success": True, "data": [item.to_dict(include_relations=True) for item in items], "total": len(items)}


@router.get("/department/{department_id}")
def get_department_equipment(
    department_id: int,
    include_assigned: str = "true",
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.read.own_dept"]),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj2.apps.helpdesk.services.inventory_service import InventoryService

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])

    if "admin" not in user_roles and user_id not in secretary_comp_center and "tech_desarrollo" not in user_roles and "tech_soporte" not in user_roles:
        from itcj2.core.services.departments_service import get_user_department
        user_dept = get_user_department(db, user_id)
        if not user_dept or user_dept.id != department_id:
            raise HTTPException(403, detail={"success": False, "error": "No tiene permiso para ver este departamento"})

    items = InventoryService.get_items_for_department(department_id, include_assigned.lower() == "true")
    return {"success": True, "data": [item.to_dict(include_relations=True) for item in items], "total": len(items)}


@router.get("/{item_id}")
def get_item(
    item_id: int,
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj2.apps.helpdesk.models import InventoryItem

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])

    item = db.get(InventoryItem, item_id)
    if not item or not item.is_active:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    if "admin" not in user_roles and user_id not in secretary_comp_center and "tech_soporte" not in user_roles and "tech_desarrollo" not in user_roles:
        if "department_head" in user_roles:
            from itcj2.core.services.departments_service import get_user_department
            user_dept = get_user_department(db, user_id)
            if not user_dept or item.department_id != user_dept.id:
                raise HTTPException(403, detail={"success": False, "error": "No tiene permiso para ver este equipo"})
        else:
            if item.assigned_to_user_id != user_id:
                raise HTTPException(403, detail={"success": False, "error": "No tiene permiso para ver este equipo"})

    return {"success": True, "data": item.to_dict(include_relations=True)}


@router.get("/{item_id}/tickets")
def get_item_tickets(
    item_id: int,
    request: Request,
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj2.apps.helpdesk.models import InventoryItem, Ticket, TicketInventoryItem

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])

    item = db.get(InventoryItem, item_id)
    if not item or not item.is_active:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    if "admin" not in user_roles and user_id not in secretary_comp_center and "tech_soporte" not in user_roles and "tech_desarrollo" not in user_roles:
        if "department_head" in user_roles:
            from itcj2.core.services.departments_service import get_user_department
            user_dept = get_user_department(db, user_id)
            if not user_dept or item.department_id != user_dept.id:
                raise HTTPException(403, detail={"success": False, "error": "No tiene permiso"})
        else:
            if item.assigned_to_user_id != user_id:
                raise HTTPException(403, detail={"success": False, "error": "No tiene permiso"})

    params = request.query_params
    status = params.get("status")
    page = int(params.get("page", "1"))
    per_page = min(int(params.get("per_page", "20")), 100)

    query = db.query(Ticket).join(
        TicketInventoryItem, TicketInventoryItem.ticket_id == Ticket.id
    ).filter(TicketInventoryItem.inventory_item_id == item_id).order_by(Ticket.created_at.desc())

    if status:
        query = query.filter(Ticket.status == status)

    from itcj2.models.base import paginate
    paginated = paginate(query, page=page, per_page=per_page)
    tickets = [t.to_dict(include_relations=True) for t in paginated.items]

    return {
        "success": True,
        "tickets": tickets,
        "total": paginated.total,
        "page": page,
        "per_page": per_page,
        "total_pages": paginated.pages,
    }


@router.post("", status_code=201)
def create_item(
    body: dict,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.create"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_service import InventoryService
    from itcj2.apps.helpdesk.utils.inventory_validators import InventoryValidators

    user_id = int(user["sub"])
    data = dict(body)

    is_valid, message, category = InventoryValidators.validate_category(data.get("category_id"))
    if not is_valid:
        raise HTTPException(400, detail={"success": False, "error": message})

    is_valid, message, department = InventoryValidators.validate_department(data.get("department_id"))
    if not is_valid:
        raise HTTPException(400, detail={"success": False, "error": message})

    if data.get("serial_number"):
        is_valid, message = InventoryValidators.validate_serial_number(data["serial_number"])
        if not is_valid:
            raise HTTPException(400, detail={"success": False, "error": message})

    if data.get("specifications"):
        is_valid, message, errors = InventoryValidators.validate_specifications(data["specifications"], category)
        if not is_valid:
            raise HTTPException(400, detail={"success": False, "error": message, "validation_errors": errors})

    if data.get("acquisition_date"):
        try:
            data["acquisition_date"] = datetime.fromisoformat(data["acquisition_date"].replace("Z", "+00:00")).date()
        except Exception:
            raise HTTPException(400, detail={"success": False, "error": "Fecha de adquisición inválida"})

    if data.get("warranty_expiration"):
        try:
            data["warranty_expiration"] = datetime.fromisoformat(data["warranty_expiration"].replace("Z", "+00:00")).date()
        except Exception:
            raise HTTPException(400, detail={"success": False, "error": "Fecha de garantía inválida"})

    try:
        item = InventoryService.create_item(
            data=data,
            registered_by_id=user_id,
            ip_address=request.client.host if request.client else None,
        )
        return {"success": True, "message": "Equipo registrado exitosamente", "data": item.to_dict(include_relations=True)}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail={"success": False, "error": f"Error al crear equipo: {str(e)}"})


@router.patch("/{item_id}")
def update_item(
    item_id: int,
    body: dict,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import InventoryItem
    from itcj2.apps.helpdesk.services.inventory_service import InventoryService

    user_id = int(user["sub"])
    item = db.get(InventoryItem, item_id)
    if not item or not item.is_active:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    data = dict(body)
    if data.get("warranty_expiration"):
        try:
            data["warranty_expiration"] = datetime.fromisoformat(data["warranty_expiration"].replace("Z", "+00:00")).date()
        except Exception:
            raise HTTPException(400, detail={"success": False, "error": "Fecha de garantía inválida"})

    try:
        updated_item = InventoryService.update_item(
            item_id=item_id, data=data, updated_by_id=user_id,
            ip_address=request.client.host if request.client else None,
        )
        return {"success": True, "message": "Equipo actualizado exitosamente", "data": updated_item.to_dict(include_relations=True)}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail={"success": False, "error": f"Error al actualizar: {str(e)}"})


@router.post("/{item_id}/status")
def change_item_status(
    item_id: int,
    body: dict,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import InventoryItem
    from itcj2.apps.helpdesk.services.inventory_service import InventoryService
    from itcj2.apps.helpdesk.utils.inventory_validators import InventoryValidators

    user_id = int(user["sub"])
    if not body.get("status"):
        raise HTTPException(400, detail={"success": False, "error": "Estado requerido"})

    item = db.get(InventoryItem, item_id)
    if not item or not item.is_active:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    is_valid, message = InventoryValidators.validate_status_transition(item.status, body["status"])
    if not is_valid:
        raise HTTPException(400, detail={"success": False, "error": message})

    try:
        updated_item = InventoryService.change_status(
            item_id=item_id, new_status=body["status"], changed_by_id=user_id,
            notes=body.get("notes"),
            ip_address=request.client.host if request.client else None,
        )
        return {"success": True, "message": f'Estado cambiado a {body["status"]}', "data": updated_item.to_dict(include_relations=True)}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail={"success": False, "error": f"Error: {str(e)}"})


@router.post("/{item_id}/deactivate")
def deactivate_item(
    item_id: int,
    body: dict,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.delete"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_service import InventoryService

    user_id = int(user["sub"])
    if not body.get("reason") or len(body["reason"].strip()) < 10:
        raise HTTPException(400, detail={"success": False, "error": "La razón debe tener al menos 10 caracteres"})

    try:
        item = InventoryService.deactivate_item(
            item_id=item_id, deactivated_by_id=user_id, reason=body["reason"],
            ip_address=request.client.host if request.client else None,
        )
        return {"success": True, "message": "Equipo dado de baja exitosamente", "data": item.to_dict(include_relations=True)}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail={"success": False, "error": f"Error: {str(e)}"})
