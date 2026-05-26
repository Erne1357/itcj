"""
Inventory Items API v2 — 10 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/inventory/inventory_items.py
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Body, HTTPException, Request
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

    from itcj2.apps.helpdesk.utils.inventory_access import is_comp_center_user

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])
    is_comp_center = is_comp_center_user(db, user_id)
    user_dept = None
    params = request.query_params

    query = db.query(InventoryItem).filter_by(is_active=True)

    if "admin" not in user_roles and user_id not in secretary_comp_center and "tech_desarrollo" not in user_roles and "tech_soporte" not in user_roles and not is_comp_center:
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

    campaign_id = params.get("campaign_id")
    if campaign_id:
        query = query.filter(InventoryItem.campaign_id == int(campaign_id))

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
            InventoryItem.supplier_serial.ilike(search_term),
            InventoryItem.itcj_serial.ilike(search_term),
            InventoryItem.id_tecnm.ilike(search_term),
        ))

    sort = params.get("sort", "")
    if sort == "recent":
        query = query.order_by(InventoryItem.registered_at.desc(), InventoryItem.id.desc())
    else:
        query = query.order_by(InventoryItem.id.asc())

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
    items = InventoryService.get_items_for_user(db, user_id, category_id)
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

    from itcj2.apps.helpdesk.utils.inventory_access import is_comp_center_user

    current_user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, current_user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])
    is_comp_center = is_comp_center_user(db, current_user_id)

    if "admin" not in user_roles and current_user_id not in secretary_comp_center and "tech_desarrollo" not in user_roles and "tech_soporte" not in user_roles and not is_comp_center:
        raise HTTPException(403, detail={"success": False, "error": "No tiene permiso para consultar equipos de otros usuarios"})

    items = InventoryService.get_items_for_user(db, target_user_id, category_id)
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

    from itcj2.apps.helpdesk.utils.inventory_access import is_comp_center_user

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])
    is_comp_center = is_comp_center_user(db, user_id)

    if "admin" not in user_roles and user_id not in secretary_comp_center and "tech_desarrollo" not in user_roles and "tech_soporte" not in user_roles and not is_comp_center:
        from itcj2.core.services.departments_service import get_user_department
        user_dept = get_user_department(db, user_id)
        if not user_dept or user_dept.id != department_id:
            raise HTTPException(403, detail={"success": False, "error": "No tiene permiso para ver este departamento"})

    items = InventoryService.get_items_for_department(db, department_id, include_assigned.lower() == "true")
    return {"success": True, "data": [item.to_dict(include_relations=True) for item in items], "total": len(items)}


@router.get("/{item_id}")
def get_item(
    item_id: int,
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position
    from itcj2.apps.helpdesk.models import InventoryItem
    from itcj2.apps.helpdesk.utils.inventory_access import is_comp_center_user

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])
    is_comp_center = is_comp_center_user(db, user_id)

    item = db.get(InventoryItem, item_id)
    if not item or not item.is_active:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    if "admin" not in user_roles and user_id not in secretary_comp_center and "tech_soporte" not in user_roles and "tech_desarrollo" not in user_roles and not is_comp_center:
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
    from itcj2.apps.helpdesk.utils.inventory_access import is_comp_center_user

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")
    secretary_comp_center = _get_users_with_position(db, ["secretary_comp_center"])
    is_comp_center = is_comp_center_user(db, user_id)

    item = db.get(InventoryItem, item_id)
    if not item or not item.is_active:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    if "admin" not in user_roles and user_id not in secretary_comp_center and "tech_soporte" not in user_roles and "tech_desarrollo" not in user_roles and not is_comp_center:
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
    request: Request,
    body: dict = Body(...),
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.create"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_service import InventoryService
    from itcj2.apps.helpdesk.utils.inventory_validators import InventoryValidators

    user_id = int(user["sub"])
    data = dict(body)

    is_valid, message, category = InventoryValidators.validate_category(data.get("category_id"), db=db)
    if not is_valid:
        raise HTTPException(400, detail={"success": False, "error": message})

    if data.get("department_id"):
        is_valid, message, department = InventoryValidators.validate_department(data.get("department_id"), db=db)
        if not is_valid:
            raise HTTPException(400, detail={"success": False, "error": message})

    if data.get("supplier_serial"):
        is_valid, message = InventoryValidators.validate_supplier_serial(data["supplier_serial"], db=db)
        if not is_valid:
            raise HTTPException(400, detail={"success": False, "error": message})

    if data.get("itcj_serial"):
        is_valid, message = InventoryValidators.validate_itcj_serial(data["itcj_serial"], db=db)
        if not is_valid:
            raise HTTPException(400, detail={"success": False, "error": message})

    if data.get("id_tecnm"):
        is_valid, message = InventoryValidators.validate_id_tecnm(data["id_tecnm"], db=db)
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
            db,
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


_LOCKED_FIELDS = frozenset({
    'inventory_number', 'supplier_serial', 'itcj_serial',
    'id_tecnm', 'department_id', 'category_id', 'brand', 'model',
})


@router.patch("/{item_id}")
def update_item(
    item_id: int,
    request: Request,
    body: dict = Body(...),
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.update"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import InventoryItem
    from itcj2.apps.helpdesk.services.inventory_service import InventoryService
    from itcj2.apps.helpdesk.services.inventory_history_service import InventoryHistoryService
    from itcj2.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    item = db.get(InventoryItem, item_id)
    if not item or not item.is_active:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    data = dict(body)

    # Extraer _justification antes de pasar data al service (no es campo del modelo)
    admin_justification: str | None = data.pop("_justification", None) or None

    if data.get("warranty_expiration"):
        try:
            data["warranty_expiration"] = datetime.fromisoformat(data["warranty_expiration"].replace("Z", "+00:00")).date()
        except Exception:
            raise HTTPException(400, detail={"success": False, "error": "Fecha de garantía inválida"})

    is_admin = "admin" in user_roles_in_app(db, user_id, "helpdesk")
    touched_locked = _LOCKED_FIELDS & set(data.keys())

    if item.is_locked and touched_locked and not is_admin:
        raise HTTPException(
            423,
            detail={
                "success": False,
                "error": f"El equipo está bloqueado por una campaña validada. No puedes modificar: {', '.join(sorted(touched_locked))}",
            },
        )

    # Snapshot of locked fields before update (for admin audit trail)
    pre_values = {f: getattr(item, f) for f in touched_locked} if item.is_locked and is_admin else {}

    ip = request.client.host if request.client else None
    try:
        updated_item = InventoryService.update_item(
            db,
            item_id=item_id, data=data, updated_by_id=user_id,
            ip_address=ip,
        )

        # Log per-field override events when admin edits locked fields
        if pre_values:
            for field, old_val in pre_values.items():
                new_val = getattr(updated_item, field)
                if old_val != new_val:
                    InventoryHistoryService.log_event(
                        db,
                        item_id=item_id,
                        event_type='LOCKED_FIELD_MODIFIED',
                        performed_by_id=user_id,
                        old_value={field: str(old_val) if old_val is not None else None},
                        new_value={field: str(new_val) if new_val is not None else None},
                        notes=(
                        f"Campo bloqueado modificado por admin: {field}."
                        + (f" Justificación: {admin_justification}" if admin_justification else "")
                    ),
                        ip_address=ip,
                    )
            db.commit()

        return {"success": True, "message": "Equipo actualizado exitosamente", "data": updated_item.to_dict(include_relations=True)}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail={"success": False, "error": f"Error al actualizar: {str(e)}"})


@router.post("/{item_id}/status")
def change_item_status(
    item_id: int,
    request: Request,
    body: dict = Body(...),
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
            db,
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
    request: Request,
    body: dict = Body(...),
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.delete"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models import InventoryItem
    from itcj2.apps.helpdesk.services.inventory_service import InventoryService
    from itcj2.core.services.authz_service import user_roles_in_app

    user_id = int(user["sub"])
    if not body.get("reason") or len(body["reason"].strip()) < 10:
        raise HTTPException(400, detail={"success": False, "error": "La razón debe tener al menos 10 caracteres"})

    item = db.get(InventoryItem, item_id)
    if not item or not item.is_active:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    is_admin = "admin" in user_roles_in_app(db, user_id, "helpdesk")
    if item.is_locked and not is_admin:
        raise HTTPException(
            423,
            detail={
                "success": False,
                "error": "El equipo está bloqueado por una campaña validada y no puede darse de baja.",
            },
        )

    try:
        item = InventoryService.deactivate_item(
            db,
            item_id=item_id, deactivated_by_id=user_id, reason=body["reason"],
            ip_address=request.client.host if request.client else None,
        )
        return {"success": True, "message": "Equipo dado de baja exitosamente", "data": item.to_dict(include_relations=True)}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail={"success": False, "error": f"Error: {str(e)}"})


# ── Versionado de items ────────────────────────────────────────────────────────

@router.post("/{item_id}/set-predecessor")
def set_predecessor(
    item_id: int,
    request: Request,
    body: dict = Body(...),
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.update"]),
    db: DbSession = None,
):
    """Declara el predecesor de un item (cadena lineal de versiones)."""
    from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
    from itcj2.apps.helpdesk.services.inventory_history_service import InventoryHistoryService

    user_id = int(user["sub"])
    predecessor_id = body.get("predecessor_item_id")
    if not predecessor_id:
        raise HTTPException(400, detail={"success": False, "error": "predecessor_item_id requerido"})
    predecessor_id = int(predecessor_id)

    item = db.get(InventoryItem, item_id)
    if not item or not item.is_active:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    if predecessor_id == item_id:
        raise HTTPException(400, detail={"success": False, "error": "Un equipo no puede ser su propio predecesor"})

    predecessor = db.get(InventoryItem, predecessor_id)
    if not predecessor:
        raise HTTPException(404, detail={"success": False, "error": "Equipo predecesor no encontrado"})

    # Detectar ciclo: el predecesor no puede tener a este item en su cadena
    current = predecessor
    while current.predecessor_item_id:
        if current.predecessor_item_id == item_id:
            raise HTTPException(400, detail={"success": False, "error": "Esta vinculación crearía un ciclo en la cadena de versiones"})
        current = db.get(InventoryItem, current.predecessor_item_id)

    # El predecesor no puede ya tener un sucesor distinto
    if predecessor.successor and predecessor.successor.id != item_id:
        raise HTTPException(400, detail={
            "success": False,
            "error": f"El equipo {predecessor.inventory_number} ya tiene un sucesor: {predecessor.successor.inventory_number}",
        })

    old_predecessor_id = item.predecessor_item_id
    item.predecessor_item_id = predecessor_id

    try:
        InventoryHistoryService.log_event(
            db,
            item_id=item_id,
            event_type="VERSION_LINKED",
            performed_by_id=user_id,
            old_value={"predecessor_item_id": old_predecessor_id},
            new_value={"predecessor_item_id": predecessor_id, "predecessor_number": predecessor.inventory_number},
            notes=f"Vinculado como sucesor de {predecessor.inventory_number}",
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        db.refresh(item)
        return {
            "success": True,
            "message": f"Equipo vinculado como sucesor de {predecessor.inventory_number}",
            "data": item.to_dict(include_relations=True),
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail={"success": False, "error": f"Error al vincular: {str(e)}"})


@router.delete("/{item_id}/predecessor")
def remove_predecessor(
    item_id: int,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.api.update"]),
    db: DbSession = None,
):
    """Desvincula el predecesor de un item."""
    from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
    from itcj2.apps.helpdesk.services.inventory_history_service import InventoryHistoryService

    user_id = int(user["sub"])
    item = db.get(InventoryItem, item_id)
    if not item or not item.is_active:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    if not item.predecessor_item_id:
        raise HTTPException(400, detail={"success": False, "error": "Este equipo no tiene predecesor vinculado"})

    old_predecessor = item.predecessor
    old_predecessor_id = item.predecessor_item_id
    item.predecessor_item_id = None

    try:
        InventoryHistoryService.log_event(
            db,
            item_id=item_id,
            event_type="VERSION_UNLINKED",
            performed_by_id=user_id,
            old_value={"predecessor_item_id": old_predecessor_id, "predecessor_number": old_predecessor.inventory_number if old_predecessor else None},
            new_value={"predecessor_item_id": None},
            notes=f"Desvinculado del predecesor {old_predecessor.inventory_number if old_predecessor else old_predecessor_id}",
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        db.refresh(item)
        return {"success": True, "message": "Predecesor desvinculado", "data": item.to_dict(include_relations=True)}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail={"success": False, "error": f"Error al desvincular: {str(e)}"})


@router.get("/{item_id}/version-chain")
def get_version_chain(
    item_id: int,
    user: dict = require_app("helpdesk"),
    db: DbSession = None,
):
    """Retorna la cadena completa de versiones del item (predecessores y sucesor)."""
    from itcj2.apps.helpdesk.models.inventory_item import InventoryItem

    item = db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})

    chain = item.version_chain
    chain_data = []
    for i, node in enumerate(chain):
        chain_data.append({
            "id": node.id,
            "inventory_number": node.inventory_number,
            "brand": node.brand,
            "model": node.model,
            "registered_at": node.registered_at.isoformat() if node.registered_at else None,
            "is_active": node.is_active,
            "is_current": node.id == item_id,
            "is_latest": node.is_latest_version,
        })

    # Agregar sucesor si existe y no está ya en la cadena
    if item.successor and item.successor.id not in {n.id for n in chain}:
        s = item.successor
        chain_data.append({
            "id": s.id,
            "inventory_number": s.inventory_number,
            "brand": s.brand,
            "model": s.model,
            "registered_at": s.registered_at.isoformat() if s.registered_at else None,
            "is_active": s.is_active,
            "is_current": False,
            "is_latest": s.is_latest_version,
        })

    return {"success": True, "data": chain_data, "total": len(chain_data)}
