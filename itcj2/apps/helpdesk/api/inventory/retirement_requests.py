"""
Inventory Retirement Requests API — Solicitudes de baja de equipos.
"""
import logging

from fastapi import APIRouter, Body, File, HTTPException, Request, UploadFile
from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["helpdesk-inventory-retirement"])
logger = logging.getLogger(__name__)


def _is_admin(db, user_id):
    from itcj2.core.services.authz_service import user_roles_in_app, _get_users_with_position
    roles = user_roles_in_app(db, user_id, "helpdesk")
    sec = _get_users_with_position(db, ["secretary_comp_center"])
    return "admin" in roles or user_id in sec


# ── Listado ────────────────────────────────────────────────────────────────────

@router.get("")
def list_requests(
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.retirement.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_retirement_service import InventoryRetirementService

    user_id = int(user["sub"])
    params = request.query_params
    filters = {
        "status":   params.get("status"),
        "folio":    params.get("folio"),
        "page":     int(params.get("page", "1")),
        "per_page": int(params.get("per_page", "20")),
    }
    result = InventoryRetirementService.get_requests(db, user_id, _is_admin(db, user_id), filters)
    return {"success": True, **result}


# ── Crear solicitud ────────────────────────────────────────────────────────────

@router.post("", status_code=201)
def create_request(
    request: Request,
    body: dict = Body(...),
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.retirement.api.create"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_retirement_service import InventoryRetirementService

    user_id = int(user["sub"])
    reason = body.get("reason", "")
    item_ids = body.get("item_ids", [])
    notes_map = body.get("notes_map", {})

    try:
        req = InventoryRetirementService.create_request(db, reason, user_id)
        if item_ids:
            req = InventoryRetirementService.add_items(db, req.id, item_ids, notes_map, user_id)
        return {"success": True, "message": f"Solicitud {req.folio} creada", "data": req.to_dict(include_items=True)}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail={"success": False, "error": str(e)})


# ── Detalle ────────────────────────────────────────────────────────────────────

@router.get("/{request_id}")
def get_request(
    request_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.retirement.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.models.inventory_retirement_request import InventoryRetirementRequest

    user_id = int(user["sub"])
    req = db.get(InventoryRetirementRequest, request_id)
    if not req:
        raise HTTPException(404, detail={"success": False, "error": "Solicitud no encontrada"})

    if not _is_admin(db, user_id) and req.requested_by_id != user_id:
        raise HTTPException(403, detail={"success": False, "error": "Sin acceso a esta solicitud"})

    return {"success": True, "data": req.to_dict(include_items=True)}


# ── Agregar equipos ────────────────────────────────────────────────────────────

@router.post("/{request_id}/items")
def add_items(
    request_id: int,
    body: dict = Body(...),
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.retirement.api.create"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_retirement_service import InventoryRetirementService

    user_id = int(user["sub"])
    item_ids  = body.get("item_ids", [])
    notes_map = body.get("notes_map", {})

    if not item_ids:
        raise HTTPException(400, detail={"success": False, "error": "item_ids requerido"})

    try:
        req = InventoryRetirementService.add_items(db, request_id, item_ids, notes_map, user_id)
        return {"success": True, "data": req.to_dict(include_items=True)}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})


# ── Quitar equipo ──────────────────────────────────────────────────────────────

@router.delete("/{request_id}/items/{item_id}")
def remove_item(
    request_id: int,
    item_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.retirement.api.create"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_retirement_service import InventoryRetirementService

    user_id = int(user["sub"])
    try:
        req = InventoryRetirementService.remove_item(db, request_id, item_id, user_id)
        return {"success": True, "data": req.to_dict(include_items=True)}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})


# ── Enviar para revisión ───────────────────────────────────────────────────────

@router.post("/{request_id}/submit")
def submit_request(
    request_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.retirement.api.create"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_retirement_service import InventoryRetirementService

    user_id = int(user["sub"])
    try:
        req = InventoryRetirementService.submit_request(db, request_id, user_id)
        return {"success": True, "message": f"Solicitud {req.folio} enviada para revisión", "data": req.to_dict()}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})


# ── Aprobar ────────────────────────────────────────────────────────────────────

@router.post("/{request_id}/approve")
def approve_request(
    request_id: int,
    request: Request,
    body: dict = Body(...),
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.retirement.api.approve"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_retirement_service import InventoryRetirementService

    user_id = int(user["sub"])
    ip = request.client.host if request.client else None
    try:
        req = InventoryRetirementService.approve_request(db, request_id, user_id, body.get("review_notes"), ip)
        return {"success": True, "message": f"Solicitud {req.folio} aprobada. Equipos dados de baja.", "data": req.to_dict()}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail={"success": False, "error": str(e)})


# ── Rechazar ───────────────────────────────────────────────────────────────────

@router.post("/{request_id}/reject")
def reject_request(
    request_id: int,
    body: dict = Body(...),
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.retirement.api.approve"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_retirement_service import InventoryRetirementService

    user_id = int(user["sub"])
    try:
        req = InventoryRetirementService.reject_request(db, request_id, user_id, body.get("review_notes", ""))
        return {"success": True, "message": f"Solicitud {req.folio} rechazada", "data": req.to_dict()}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})


# ── Cancelar ───────────────────────────────────────────────────────────────────

@router.post("/{request_id}/cancel")
def cancel_request(
    request_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.retirement.api.cancel"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_retirement_service import InventoryRetirementService

    user_id = int(user["sub"])
    try:
        req = InventoryRetirementService.cancel_request(db, request_id, user_id)
        return {"success": True, "message": f"Solicitud {req.folio} cancelada", "data": req.to_dict()}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})


# ── Adjuntar documento ─────────────────────────────────────────────────────────

@router.post("/{request_id}/attach")
async def attach_document(
    request_id: int,
    file: UploadFile = File(...),
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.retirement.api.create"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_retirement_service import InventoryRetirementService

    user_id = int(user["sub"])
    try:
        req = InventoryRetirementService.attach_document(
            db, request_id, file.file, file.filename, user_id
        )
        return {"success": True, "message": "Documento adjuntado", "data": req.to_dict()}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        logger.error(f"attach_document error: {e}")
        raise HTTPException(500, detail={"success": False, "error": str(e)})


# ── Generar formato PDF ────────────────────────────────────────────────────────

@router.get("/{request_id}/generate-format")
def generate_format(
    request_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.retirement.api.create"]),
    db: DbSession = None,
):
    return {
        "success": False,
        "message": "Generación de formato pendiente. El formato oficial aún no ha sido configurado. Adjunta el documento manualmente.",
        "status": 501,
    }
