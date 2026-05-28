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
    from itcj2.apps.helpdesk.utils.inventory_access import is_comp_center_user
    roles = user_roles_in_app(db, user_id, "helpdesk")
    sec = _get_users_with_position(db, ["secretary_comp_center"])
    return "admin" in roles or user_id in sec or is_comp_center_user(db, user_id)


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


# ── Descargar documento adjunto ────────────────────────────────────────────────

@router.get("/{request_id}/document")
def download_document(
    request_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.retirement.api.read"]),
    db: DbSession = None,
):
    """Descarga el documento adjunto a la solicitud.

    Permitido para: solicitante, admin/CC, y cualquiera de los firmantes del flujo
    (head_mat_services, subdirector_admin_services, director, head_comp_center).
    """
    import os
    from fastapi.responses import FileResponse
    from itcj2.apps.helpdesk.models.inventory_retirement_request import InventoryRetirementRequest

    req = db.get(InventoryRetirementRequest, request_id)
    if not req:
        raise HTTPException(404, detail={"success": False, "error": "Solicitud no encontrada"})
    if not req.document_path:
        raise HTTPException(404, detail={"success": False, "error": "Esta solicitud no tiene documento adjunto"})

    user_id = int(user["sub"])
    if not _is_admin(db, user_id) and req.requested_by_id != user_id:
        from itcj2.core.services.authz_service import _get_users_with_position
        signer_ids = set(_get_users_with_position(db, [
            "head_mat_services", "subdirector_admin_services", "director", "head_comp_center",
        ]))
        if user_id not in signer_ids:
            raise HTTPException(403, detail={"success": False, "error": "Sin acceso a esta solicitud"})

    if not os.path.exists(req.document_path):
        logger.error(f"download_document: archivo no encontrado en disco: {req.document_path} (req {req.id})")
        raise HTTPException(404, detail={"success": False, "error": "Archivo no encontrado en el servidor"})

    filename = req.document_original_name or os.path.basename(req.document_path)
    # Forzar descarga: ad-blockers bloquean preview inline. Usuario abre el archivo localmente.
    return FileResponse(
        path=req.document_path,
        filename=filename,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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


# ── Generar oficio Excel (plantilla oficial) ──────────────────────────────────

@router.get("/{request_id}/generate-document")
def generate_document(
    request_id: int,
    format: str = "xlsx",   # PDF deshabilitado; sólo xlsx
    user: dict = require_perms("helpdesk", [
        "helpdesk.inventory.retirement.api.create",
        "helpdesk.inventory.retirement.api.read",
        "helpdesk.retirement.sign.recursos_materiales",
        "helpdesk.retirement.sign.subdirector",
        "helpdesk.retirement.sign.director",
        "helpdesk.retirement.sign.comp_center",
    ]),
    db: DbSession = None,
):
    """
    Genera el oficio oficial de baja en Excel editando la plantilla oficial.
    PDF está deshabilitado para preservar el formato institucional.
    """
    from fastapi.responses import Response
    from itcj2.apps.helpdesk.services.retirement_document_service import RetirementDocumentService
    from itcj2.apps.helpdesk.models.inventory_retirement_request import InventoryRetirementRequest

    req = db.get(InventoryRetirementRequest, request_id)
    if not req:
        raise HTTPException(404, detail={"success": False, "error": "Solicitud no encontrada"})

    user_id = int(user["sub"])
    # Permitir acceso a: admin, solicitante, y firmantes (incluido Jefe CC)
    if not _is_admin(db, user_id) and req.requested_by_id != user_id:
        from itcj2.core.services.authz_service import _get_users_with_position
        signer_ids = set(_get_users_with_position(db, [
            "head_mat_services", "subdirector_admin_services", "director", "head_comp_center",
        ]))
        if user_id not in signer_ids:
            raise HTTPException(403, detail={"success": False, "error": "Sin acceso a esta solicitud"})

    # Sólo se genera Excel. PDF deshabilitado para preservar el formato oficial.
    try:
        content = RetirementDocumentService.fill_excel_template(req, db=db)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"{req.folio}.xlsx"
    except RuntimeError as e:
        raise HTTPException(500, detail={"success": False, "error": str(e)})
    except Exception as e:
        logger.error(f"generate_document error (request_id={request_id}, format={format}): {e}")
        raise HTTPException(500, detail={"success": False, "error": "Error al generar el documento"})

    # Si la solicitud está en DRAFT, marcar que el oficio fue generado (habilita el flujo multi-firma)
    if req.status == "DRAFT" and req.oficio_data is None:
        from datetime import datetime as _dt
        req.oficio_data = {"type": "system_generated", "generated_at": _dt.utcnow().isoformat()}
        req.format_generated_at = _dt.utcnow()
        db.commit()

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Enviar al flujo de firmas ──────────────────────────────────────────────────

@router.post("/{request_id}/submit-for-approval")
def submit_for_approval(
    request_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.retirement.api.create"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_retirement_service import InventoryRetirementService

    user_id = int(user["sub"])
    try:
        req = InventoryRetirementService.submit_for_approval(db, request_id, user_id)
        return {
            "success": True,
            "message": f"Solicitud {req.folio} enviada al flujo de aprobación",
            "data": req.to_dict(),
        }
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        logger.error(f"submit_for_approval error: {e}")
        db.rollback()
        raise HTTPException(500, detail={"success": False, "error": "Error interno"})


# ── Firmar / rechazar ──────────────────────────────────────────────────────────

@router.post("/{request_id}/sign")
def sign_request(
    request_id: int,
    body: dict = Body(...),
    user: dict = require_perms("helpdesk", [
        "helpdesk.retirement.sign.recursos_materiales",
        "helpdesk.retirement.sign.subdirector",
        "helpdesk.retirement.sign.director",
        "helpdesk.retirement.sign.comp_center",
    ]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_retirement_service import InventoryRetirementService

    user_id = int(user["sub"])
    action = body.get("action", "").upper()
    notes = body.get("notes")

    if action not in ("APPROVED", "REJECTED"):
        raise HTTPException(400, detail={"success": False, "error": "El campo 'action' debe ser APPROVED o REJECTED"})

    try:
        req = InventoryRetirementService.sign_request(db, request_id, user_id, action, notes)
        action_label = "aprobada" if action == "APPROVED" else "rechazada"
        return {
            "success": True,
            "message": f"Solicitud {req.folio} {action_label}",
            "data": req.to_dict(),
        }
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        logger.error(f"sign_request error: {e}")
        db.rollback()
        raise HTTPException(500, detail={"success": False, "error": "Error interno"})


# ── Re-enviar tras rechazo ─────────────────────────────────────────────────────

@router.post("/{request_id}/resubmit")
def resubmit_request(
    request_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.retirement.api.create"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_retirement_service import InventoryRetirementService

    user_id = int(user["sub"])
    try:
        req = InventoryRetirementService.resubmit_request(db, request_id, user_id)
        return {
            "success": True,
            "message": f"Solicitud {req.folio} regresada a borrador para corrección",
            "data": req.to_dict(),
        }
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        logger.error(f"resubmit_request error: {e}")
        db.rollback()
        raise HTTPException(500, detail={"success": False, "error": "Error interno"})


# ── Estado de firmas ───────────────────────────────────────────────────────────

@router.get("/{request_id}/signatures")
def get_signatures(
    request_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.retirement.api.read"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services.inventory_retirement_service import InventoryRetirementService

    try:
        timeline = InventoryRetirementService.get_signatures(db, request_id)
        return {"success": True, "data": timeline}
    except ValueError as e:
        raise HTTPException(404, detail={"success": False, "error": str(e)})
