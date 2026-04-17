"""
Inventory Campaigns API — Campañas de inventario.

Rutas (prefix: /api/help-desk/v2/inventory/campaigns):
  GET    /                              → Listar campañas (filtradas por rol)
  POST   /                              → Crear campaña (CC/Admin)
  GET    /{id}                          → Detalle de campaña
  POST   /{id}/close                    → Cerrar campaña → PENDING_VALIDATION
  POST   /{id}/reopen                   → Reabrir campaña rechazada (admin only)
  GET    /{id}/comparison               → Comparación items nuevos vs pre-existentes
  GET    /{id}/validation-data          → Datos completos para la vista de validación
  POST   /{id}/approve                  → Aprobar campaña (jefe de dpto)
  POST   /{id}/reject                   → Rechazar campaña con observaciones (jefe de dpto)
  POST   /{id}/items/bulk-assign        → Asignación masiva retroactiva de items
  DELETE /{id}/items/{item_id}          → Desvincular item de campaña (solo OPEN)
  POST   /{id}/items/{item_id}/unlock   → Desbloquear item validado (admin only)
"""
import logging

from fastapi import APIRouter, HTTPException, Request

from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.helpdesk.schemas.inventory import (
    CampaignApproveRequest,
    CampaignBulkAssignRequest,
    CampaignCreateRequest,
    CampaignRejectRequest,
    ItemUnlockRequest,
)

router = APIRouter(tags=["helpdesk-inventory-campaigns"])
logger = logging.getLogger(__name__)


# ── Helpers internos ───────────────────────────────────────────────────────────

def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _is_admin(db, user_id: int) -> bool:
    from itcj2.core.services.authz_service import user_roles_in_app
    return "admin" in user_roles_in_app(db, user_id, "helpdesk")


def _is_admin_or_cc(db, user_id: int) -> bool:
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.apps.helpdesk.utils.inventory_access import is_comp_center_user
    roles = user_roles_in_app(db, user_id, "helpdesk")
    return "admin" in roles or is_comp_center_user(db, user_id)


def _get_campaign_or_404(db, campaign_id: int):
    from itcj2.apps.helpdesk.models.inventory_campaign import InventoryCampaign
    campaign = db.get(InventoryCampaign, campaign_id)
    if not campaign:
        raise HTTPException(404, detail={"success": False, "error": "Campaña no encontrada"})
    return campaign


# ── GET / — Listar campañas ────────────────────────────────────────────────────

@router.get("")
def list_campaigns(
    department_id: int | None = None,
    status: str | None = None,
    folio: str | None = None,
    academic_period_id: int | None = None,
    page: int = 1,
    per_page: int = 20,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.campaign.api.read"]),
    db: DbSession = None,
):
    """
    Lista campañas con paginación y filtros.
    Los jefes de departamento ven automáticamente solo su departamento.
    """
    from itcj2.core.services.authz_service import user_roles_in_app
    from itcj2.core.services.departments_service import get_user_department
    from itcj2.apps.helpdesk.services.campaign_service import CampaignService

    user_id = int(user["sub"])
    user_roles = user_roles_in_app(db, user_id, "helpdesk")

    # Jefes de departamento solo ven su propio departamento
    forced_dept_id: int | None = None
    if "department_head" in user_roles and not _is_admin_or_cc(db, user_id):
        dept = get_user_department(db, user_id)
        if not dept:
            return {
                "success": True,
                "campaigns": [],
                "total": 0,
                "page": page,
                "per_page": per_page,
                "total_pages": 0,
            }
        forced_dept_id = dept.id

    filters = {
        "department_id": department_id,
        "status": status,
        "folio": folio,
        "academic_period_id": academic_period_id,
        "page": page,
        "per_page": per_page,
    }
    result = CampaignService.get_campaigns(db, filters=filters, department_id=forced_dept_id)
    return {"success": True, **result}


# ── POST / — Crear campaña ─────────────────────────────────────────────────────

@router.post("", status_code=201)
def create_campaign(
    request: Request,
    body: CampaignCreateRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.campaign.api.create"]),
    db: DbSession = None,
):
    """Crea una nueva campaña en estado OPEN para el departamento indicado."""
    from itcj2.apps.helpdesk.services.campaign_service import CampaignService

    user_id = int(user["sub"])
    try:
        campaign = CampaignService.create_campaign(
            db=db,
            department_id=body.department_id,
            title=body.title,
            notes=body.notes,
            academic_period_id=body.academic_period_id,
            created_by_id=user_id,
            ip=_client_ip(request),
        )
        return {
            "success": True,
            "message": f"Campaña {campaign.folio} creada exitosamente",
            "data": campaign.to_dict(include_relations=True),
        }
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        logger.error("create_campaign: error inesperado: %s", e, exc_info=True)
        raise HTTPException(500, detail={"success": False, "error": "Error interno al crear la campaña"})


# ── GET /{id} — Detalle ────────────────────────────────────────────────────────

@router.get("/{campaign_id}")
def get_campaign(
    campaign_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.campaign.api.read"]),
    db: DbSession = None,
):
    """Retorna el detalle completo de una campaña."""
    campaign = _get_campaign_or_404(db, campaign_id)
    return {"success": True, "data": campaign.to_dict(include_relations=True)}


# ── POST /{id}/close — Cerrar campaña ─────────────────────────────────────────

@router.post("/{campaign_id}/close")
def close_campaign(
    campaign_id: int,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.campaign.api.manage"]),
    db: DbSession = None,
):
    """
    Cierra la campaña para enviarla a validación del jefe de departamento.
    OPEN → PENDING_VALIDATION. Notifica automáticamente a los jefes.
    """
    from itcj2.apps.helpdesk.services.campaign_service import CampaignService

    user_id = int(user["sub"])
    try:
        campaign = CampaignService.close_campaign(
            db=db,
            campaign_id=campaign_id,
            closed_by_id=user_id,
            ip=_client_ip(request),
        )
        return {
            "success": True,
            "message": "Campaña cerrada y enviada a validación del jefe de departamento",
            "data": campaign.to_dict(include_relations=True),
        }
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        logger.error("close_campaign %d: %s", campaign_id, e, exc_info=True)
        raise HTTPException(500, detail={"success": False, "error": "Error interno al cerrar la campaña"})


# ── POST /{id}/reopen — Reabrir campaña rechazada (admin only) ────────────────

@router.post("/{campaign_id}/reopen")
def reopen_campaign(
    campaign_id: int,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.campaign.api.manage"]),
    db: DbSession = None,
):
    """
    Reabre una campaña rechazada para que el CC pueda corregirla.
    REJECTED → OPEN. Solo admin puede ejecutar esta acción.
    """
    from itcj2.apps.helpdesk.services.campaign_service import CampaignService

    user_id = int(user["sub"])
    if not _is_admin(db, user_id):
        raise HTTPException(403, detail={"success": False, "error": "Solo admin puede reabrir campañas rechazadas"})

    try:
        campaign = CampaignService.reopen_campaign(
            db=db,
            campaign_id=campaign_id,
            reopened_by_id=user_id,
            ip=_client_ip(request),
        )
        return {
            "success": True,
            "message": "Campaña reabierta. El CC puede corregir y volver a cerrar.",
            "data": campaign.to_dict(include_relations=True),
        }
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        logger.error("reopen_campaign %d: %s", campaign_id, e, exc_info=True)
        raise HTTPException(500, detail={"success": False, "error": "Error interno al reabrir la campaña"})


# ── GET /{id}/comparison — Comparación de items ───────────────────────────────

@router.get("/{campaign_id}/comparison")
def get_campaign_comparison(
    campaign_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.campaign.api.read"]),
    db: DbSession = None,
):
    """
    Retorna la comparación de items para la vista de validación:
    items nuevos (en esta campaña) vs items pre-existentes del departamento.
    Incluye diferencias campo a campo para items con predecesor.
    """
    from itcj2.apps.helpdesk.services.campaign_service import CampaignService

    try:
        data = CampaignService.get_campaign_comparison(db, campaign_id)
        return {"success": True, "data": data}
    except ValueError as e:
        raise HTTPException(404, detail={"success": False, "error": str(e)})


# ── GET /{id}/validation-data — Datos completos para página de validación ──────

@router.get("/{campaign_id}/validation-data")
def get_validation_data(
    campaign_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.campaign.api.validate"]),
    db: DbSession = None,
):
    """
    Datos completos para la página de validación del jefe de departamento.
    Solo disponible cuando la campaña está en PENDING_VALIDATION.
    Incluye comparación de items + historial de validaciones anteriores.
    """
    from itcj2.apps.helpdesk.services.campaign_service import CampaignService

    campaign = _get_campaign_or_404(db, campaign_id)
    if not campaign.is_pending_validation:
        raise HTTPException(
            400,
            detail={
                "success": False,
                "error": f"La campaña debe estar en PENDING_VALIDATION para validar (actual: {campaign.status})",
            },
        )

    try:
        comparison = CampaignService.get_campaign_comparison(db, campaign_id)
        validation_history = [v.to_dict() for v in campaign.validation_history]
        return {
            "success": True,
            "data": {
                **comparison,
                "validation_history": validation_history,
            },
        }
    except ValueError as e:
        raise HTTPException(404, detail={"success": False, "error": str(e)})


# ── POST /{id}/approve — Aprobar campaña (jefe de dpto) ───────────────────────

@router.post("/{campaign_id}/approve")
def approve_campaign(
    campaign_id: int,
    request: Request,
    body: CampaignApproveRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.campaign.api.validate"]),
    db: DbSession = None,
):
    """
    Aprueba la campaña. PENDING_VALIDATION → VALIDATED.
    Bloquea todos los items de la campaña y notifica al CC.
    """
    from itcj2.apps.helpdesk.services.campaign_service import CampaignService

    user_id = int(user["sub"])
    try:
        campaign = CampaignService.validate_campaign(
            db=db,
            campaign_id=campaign_id,
            action="approve",
            performed_by_id=user_id,
            notes=body.notes,
            ip=_client_ip(request),
        )
        return {
            "success": True,
            "message": f"Campaña aprobada. {campaign.items_count} equipos han quedado bloqueados.",
            "data": campaign.to_dict(include_relations=True),
        }
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        logger.error("approve_campaign %d: %s", campaign_id, e, exc_info=True)
        raise HTTPException(500, detail={"success": False, "error": "Error interno al aprobar la campaña"})


# ── POST /{id}/reject — Rechazar campaña (jefe de dpto) ───────────────────────

@router.post("/{campaign_id}/reject")
def reject_campaign(
    campaign_id: int,
    request: Request,
    body: CampaignRejectRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.campaign.api.validate"]),
    db: DbSession = None,
):
    """
    Rechaza la campaña con observaciones. PENDING_VALIDATION → REJECTED.
    Los items NO se bloquean. Notifica al CC.
    """
    from itcj2.apps.helpdesk.services.campaign_service import CampaignService

    user_id = int(user["sub"])
    try:
        campaign = CampaignService.validate_campaign(
            db=db,
            campaign_id=campaign_id,
            action="reject",
            performed_by_id=user_id,
            notes=body.notes,
            ip=_client_ip(request),
        )
        return {
            "success": True,
            "message": "Campaña rechazada. El CC ha sido notificado para realizar correcciones.",
            "data": campaign.to_dict(include_relations=True),
        }
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        logger.error("reject_campaign %d: %s", campaign_id, e, exc_info=True)
        raise HTTPException(500, detail={"success": False, "error": "Error interno al rechazar la campaña"})


# ── POST /{id}/items/bulk-assign — Asignación masiva retroactiva ──────────────
# IMPORTANTE: definir antes de /{id}/items/{item_id} para evitar colisiones de ruta

@router.post("/{campaign_id}/items/bulk-assign")
def bulk_assign_items(
    campaign_id: int,
    request: Request,
    body: CampaignBulkAssignRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.campaign.api.manage"]),
    db: DbSession = None,
):
    """
    Asigna en masa items pre-existentes (campaign_id=NULL) a esta campaña.
    Útil para retroactivamente incorporar equipos al levantamiento activo.
    Solo disponible mientras la campaña esté en OPEN.
    """
    from itcj2.apps.helpdesk.services.campaign_service import CampaignService

    user_id = int(user["sub"])
    try:
        result = CampaignService.bulk_assign_items(
            db=db,
            campaign_id=campaign_id,
            item_ids=body.item_ids,
            assigned_by_id=user_id,
            ip=_client_ip(request),
        )
        assigned_count = len(result["assigned"])
        return {
            "success": True,
            "message": f"{assigned_count} equipo(s) asignado(s) a la campaña",
            "data": result,
        }
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        logger.error("bulk_assign_items campaign %d: %s", campaign_id, e, exc_info=True)
        raise HTTPException(500, detail={"success": False, "error": "Error interno al asignar los equipos"})


# ── DELETE /{id}/items/{item_id} — Desvincular item ───────────────────────────

@router.delete("/{campaign_id}/items/{item_id}")
def unassign_item(
    campaign_id: int,
    item_id: int,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.campaign.api.manage"]),
    db: DbSession = None,
):
    """
    Desvincula un item de la campaña. Solo disponible mientras la campaña esté OPEN.
    El item queda con campaign_id=NULL (puede asignarse a otra campaña).
    """
    from itcj2.apps.helpdesk.services.campaign_service import CampaignService

    user_id = int(user["sub"])
    try:
        item = CampaignService.unassign_item(
            db=db,
            campaign_id=campaign_id,
            item_id=item_id,
            unassigned_by_id=user_id,
            ip=_client_ip(request),
        )
        return {"success": True, "message": "Equipo desvinculado de la campaña", "data": item.to_dict()}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        logger.error("unassign_item campaign %d item %d: %s", campaign_id, item_id, e, exc_info=True)
        raise HTTPException(500, detail={"success": False, "error": "Error interno al desvincular el equipo"})


# ── POST /{id}/items/{item_id}/unlock — Desbloquear item (admin only) ──────────

@router.post("/{campaign_id}/items/{item_id}/unlock")
def unlock_item(
    campaign_id: int,
    item_id: int,
    request: Request,
    body: ItemUnlockRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.campaign.api.manage"]),
    db: DbSession = None,
):
    """
    Desbloquea un item que fue bloqueado tras la validación de la campaña.
    Solo admin puede ejecutar esta acción. Requiere justificación.
    El evento queda registrado en el historial del equipo.
    """
    from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
    from itcj2.apps.helpdesk.services.inventory_history_service import InventoryHistoryService

    user_id = int(user["sub"])
    if not _is_admin(db, user_id):
        raise HTTPException(403, detail={"success": False, "error": "Solo admin puede desbloquear equipos validados"})

    item = db.get(InventoryItem, item_id)
    if not item or not item.is_active:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})
    if item.locked_campaign_id != campaign_id:
        raise HTTPException(
            400,
            detail={"success": False, "error": "El equipo no fue bloqueado por esta campaña"},
        )
    if not item.is_locked:
        raise HTTPException(400, detail={"success": False, "error": "El equipo no está bloqueado"})

    try:
        item.is_locked = False
        InventoryHistoryService.log_event(
            db=db,
            item_id=item_id,
            event_type="ITEM_UNLOCKED",
            performed_by_id=user_id,
            new_value={"is_locked": False, "justification": body.justification, "campaign_id": campaign_id},
            ip_address=_client_ip(request),
        )
        db.commit()
        db.refresh(item)
        return {"success": True, "message": "Equipo desbloqueado correctamente", "data": item.to_dict()}
    except Exception as e:
        db.rollback()
        logger.error("unlock_item campaign %d item %d: %s", campaign_id, item_id, e, exc_info=True)
        raise HTTPException(500, detail={"success": False, "error": "Error interno al desbloquear el equipo"})
