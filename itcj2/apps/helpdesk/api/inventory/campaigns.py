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


def _get_campaign_or_404(db, campaign_id: int):
    from itcj2.apps.helpdesk.models.inventory_campaign import InventoryCampaign
    campaign = db.get(InventoryCampaign, campaign_id)
    if not campaign:
        raise HTTPException(404, detail={"success": False, "error": "Campaña no encontrada"})
    return campaign


# Ancla de subárbol propia de campañas (procedencia): el jefe con este permiso ve
# su departamento ∪ subárbol; el resto de acceso completo (admin/CC/técnicos/
# .read.all de inventario) sigue viendo todas.
_CAMPAIGN_SUBTREE_PERMS = {"helpdesk.inventory.campaign.api.read.subtree"}


def _get_campaign_in_scope(db, user, campaign_id: int):
    """Como ``_get_campaign_or_404`` pero además exige que el departamento de la
    campaña esté dentro del scope visible del usuario.

    Los ids de campaña son secuenciales: sin este check, cualquier portador de
    ``.campaign.api.read``/``.validate`` podía consultar el detalle o el
    inventario agrupado de una campaña de OTRO departamento con solo adivinar el
    id. Fuera de scope ⇒ 404 (no revela ni siquiera que la campaña existe).
    """
    from itcj2.apps.helpdesk.utils.inventory_access import visible_department_ids

    campaign = _get_campaign_or_404(db, campaign_id)
    visible = visible_department_ids(db, user, extra_subtree_perms=_CAMPAIGN_SUBTREE_PERMS)
    if visible is not None and campaign.department_id not in visible:
        raise HTTPException(404, detail={"success": False, "error": "Campaña no encontrada"})
    return campaign


def _list_campaigns_query(db, filters: dict, department_ids) -> dict:
    """Réplica de ``CampaignService.get_campaigns`` que soporta un CONJUNTO de
    departamentos (scope por subárbol) — el service solo filtra por ``==`` un
    ``department_id`` escalar (fuera del alcance de este fix, no se toca).
    """
    from itcj2.apps.helpdesk.models.inventory_campaign import InventoryCampaign

    query = db.query(InventoryCampaign).filter(
        InventoryCampaign.department_id.in_(department_ids or {-1})
    )

    if filters.get("status"):
        query = query.filter(InventoryCampaign.status == filters["status"].upper())
    if filters.get("academic_period_id"):
        query = query.filter(InventoryCampaign.academic_period_id == int(filters["academic_period_id"]))
    if filters.get("folio"):
        query = query.filter(InventoryCampaign.folio.ilike(f"%{filters['folio']}%"))

    query = query.order_by(InventoryCampaign.created_at.desc())

    page = max(1, int(filters.get("page", 1)))
    per_page = min(100, int(filters.get("per_page", 20)))
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "campaigns": [c.to_dict(include_relations=True) for c in items],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }


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

    El scope se decide por PERMISO (procedencia), no por rol: cualquier portador
    de ``.campaign.api.read`` que NO tenga acceso completo (admin/CC/técnicos/
    ``.read.all`` de inventario) queda acotado a su departamento ∪ subárbol vía
    ``visible_department_ids`` — antes solo se acotaba si el usuario traía
    literalmente el ROL ``department_head``, así que un portador del permiso por
    puesto (sin ese rol) veía TODAS las campañas de todos los departamentos.
    """
    from itcj2.apps.helpdesk.services.campaign_service import CampaignService
    from itcj2.apps.helpdesk.utils.inventory_access import visible_department_ids

    visible = visible_department_ids(db, user, extra_subtree_perms=_CAMPAIGN_SUBTREE_PERMS)

    filters = {
        "department_id": department_id,
        "status": status,
        "folio": folio,
        "academic_period_id": academic_period_id,
        "page": page,
        "per_page": per_page,
    }

    if visible is None:
        # Ve todo: comportamiento previo de admin/CC/técnicos — el
        # ?department_id= se honra tal cual (o ninguno, ve todas).
        result = CampaignService.get_campaigns(db, filters=filters, department_id=None)
        return {"success": True, **result}

    # Acotado a departamento(s): el ?department_id= NUNCA sustituye el scope,
    # solo lo intersecta (fuera de scope ⇒ vacío), igual que items.py::get_items.
    wanted = (visible & {department_id}) if department_id else visible
    result = _list_campaigns_query(db, filters, department_ids=wanted)
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
    """Retorna el detalle completo de una campaña (dentro del scope del usuario)."""
    campaign = _get_campaign_in_scope(db, user, campaign_id)
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

    _get_campaign_in_scope(db, user, campaign_id)
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
            validator=user,
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
            validator=user,
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


# ── GET /{id}/validation-groups — Grupos con diff para vista de validación ────

@router.get("/{campaign_id}/validation-groups")
def get_validation_groups(
    campaign_id: int,
    user: dict = require_perms("helpdesk", [
        "helpdesk.inventory.campaign.api.read",
        "helpdesk.inventory.campaign.api.validate",
    ]),
    db: DbSession = None,
):
    """
    Devuelve los grupos del departamento de la campaña, comparando el estado
    capturado al cerrar (initial_groups_snapshot) contra el estado actual.

    Por cada grupo retorna:
      - items_current: items actualmente en el grupo
      - items_added:   items que entraron durante la campaña
      - items_removed: items que salieron del grupo (con su destino actual:
                       'sin grupo' o 'movido a otro grupo X')
      - new_group:     True si el grupo se creó durante la campaña
    """
    from itcj2.apps.helpdesk.models.inventory_group import InventoryGroup
    from itcj2.apps.helpdesk.models.inventory_item import InventoryItem

    campaign = _get_campaign_in_scope(db, user, campaign_id)
    initial_snapshot = campaign.initial_groups_snapshot or []

    # Índice del snapshot inicial por id de grupo
    initial_by_id = {g["id"]: g for g in initial_snapshot}

    # Estado actual de grupos del depto
    current_groups = (
        db.query(InventoryGroup)
        .filter(
            InventoryGroup.department_id == campaign.department_id,
            InventoryGroup.is_active.is_(True),
        )
        .order_by(InventoryGroup.name.asc())
        .all()
    )

    def _item_lite(it: InventoryItem) -> dict:
        return {
            "id": it.id,
            "inventory_number": it.inventory_number,
            "brand": it.brand,
            "model": it.model,
            "in_current_campaign": it.campaign_id == campaign_id,
            "is_locked": it.is_locked,
            "group_id": it.group_id,
        }

    # Cache: id -> nombre de grupo (para mostrar destino de items movidos)
    group_name_by_id = {g.id: g.name for g in current_groups}

    result = []
    seen_ids = set()

    for g in current_groups:
        seen_ids.add(g.id)
        current_items = list(g.items.filter(InventoryItem.is_active.is_(True)).all())
        current_ids = {it.id for it in current_items}

        initial = initial_by_id.get(g.id)
        initial_ids = set(initial["item_ids"]) if initial else set()

        added_ids   = current_ids - initial_ids
        removed_ids = initial_ids - current_ids
        kept_ids    = current_ids & initial_ids

        items_added = [
            _item_lite(it) for it in current_items if it.id in added_ids
        ]
        items_current = [_item_lite(it) for it in current_items]

        # Para items removidos, buscar su estado actual (otro grupo o NULL)
        removed_items_data = []
        if removed_ids:
            removed_items = (
                db.query(InventoryItem)
                .filter(InventoryItem.id.in_(removed_ids))
                .all()
            )
            for it in removed_items:
                destino = "Sin grupo"
                if it.group_id and it.group_id != g.id:
                    destino = f"Movido a: {group_name_by_id.get(it.group_id, '?')}"
                if not it.is_active:
                    destino = "Dado de baja"
                removed_items_data.append({
                    **_item_lite(it),
                    "destino": destino,
                })

        result.append({
            "id":           g.id,
            "name":         g.name,
            "code":         g.code,
            "group_type":   g.group_type,
            "building":     g.building,
            "floor":        g.floor,
            "new_group":    initial is None,  # grupo creado durante campaña
            "items_current": items_current,
            "items_added":   items_added,
            "items_removed": removed_items_data,
            "kept_count":    len(kept_ids),
            "added_count":   len(items_added),
            "removed_count": len(removed_items_data),
        })

    # Grupos que existían al cerrar pero ya no están activos (eliminados)
    for initial in initial_snapshot:
        if initial["id"] in seen_ids:
            continue
        result.append({
            "id":           initial["id"],
            "name":         initial["name"],
            "code":         initial["code"],
            "group_type":   initial.get("group_type"),
            "building":     None,
            "floor":        None,
            "new_group":    False,
            "deleted":      True,
            "items_current": [],
            "items_added":   [],
            "items_removed": [],
            "kept_count":    0,
            "added_count":   0,
            "removed_count": len(initial.get("item_ids", [])),
        })

    return {
        "success": True,
        "data": {
            "campaign_id": campaign_id,
            "has_initial_snapshot": bool(initial_snapshot),
            "groups": result,
            "summary": {
                "total_groups":   len(result),
                "new_groups":     sum(1 for g in result if g.get("new_group")),
                "total_added":    sum(g["added_count"] for g in result),
                "total_removed":  sum(g["removed_count"] for g in result),
            },
        },
    }


# ── GET /{id}/groups-view — Vista consolidada grupos del depto en la campaña ───

@router.get("/{campaign_id}/groups-view")
def get_groups_view(
    campaign_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.campaign.api.read"]),
    db: DbSession = None,
):
    """
    Vista consolidada para gestión de grupos durante la campaña.
    Devuelve grupos del depto con sus items + items de la campaña sin grupo.
    """
    from itcj2.apps.helpdesk.models.inventory_group import InventoryGroup
    from itcj2.apps.helpdesk.models.inventory_item import InventoryItem

    campaign = _get_campaign_in_scope(db, user, campaign_id)

    groups = (
        db.query(InventoryGroup)
        .filter(
            InventoryGroup.department_id == campaign.department_id,
            InventoryGroup.is_active.is_(True),
        )
        .order_by(InventoryGroup.name.asc())
        .all()
    )

    groups_data = []
    for g in groups:
        items = list(g.items.filter(InventoryItem.is_active.is_(True)).all())
        groups_data.append({
            **g.to_dict(include_capacities=True),
            "items": [
                {
                    "id": it.id,
                    "inventory_number": it.inventory_number,
                    "brand": it.brand,
                    "model": it.model,
                    "status": it.status,
                    "is_locked": it.is_locked,
                    "campaign_id": it.campaign_id,
                    "in_current_campaign": it.campaign_id == campaign_id,
                }
                for it in items
            ],
            "items_count": len(items),
        })

    # Items en la campaña sin grupo
    unassigned = (
        db.query(InventoryItem)
        .filter(
            InventoryItem.campaign_id == campaign_id,
            InventoryItem.group_id.is_(None),
            InventoryItem.is_active.is_(True),
        )
        .order_by(InventoryItem.inventory_number.asc())
        .all()
    )

    return {
        "success": True,
        "data": {
            "campaign": campaign.to_dict(include_relations=True),
            "groups": groups_data,
            "unassigned_items": [
                {
                    "id": it.id,
                    "inventory_number": it.inventory_number,
                    "brand": it.brand,
                    "model": it.model,
                    "status": it.status,
                    "is_locked": it.is_locked,
                }
                for it in unassigned
            ],
            "unassigned_count": len(unassigned),
            "can_edit": campaign.is_open,
        },
    }


# ── POST /{id}/groups — Crear grupo en contexto de campaña ─────────────────────

@router.post("/{campaign_id}/groups", status_code=201)
def create_group_in_campaign(
    campaign_id: int,
    request: Request,
    body: dict,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.campaign.api.manage"]),
    db: DbSession = None,
):
    """
    Crea un grupo nuevo dentro del depto de la campaña. Solo OPEN.
    Body: {name, group_type, description?, building?, floor?, location_notes?}
    """
    from itcj2.apps.helpdesk.services.inventory_group_service import InventoryGroupService

    campaign = _get_campaign_or_404(db, campaign_id)
    if not campaign.is_open:
        raise HTTPException(400, detail={
            "success": False,
            "error": f"Solo se pueden crear grupos en campañas OPEN (actual: {campaign.status})",
        })
    if not body.get("name"):
        raise HTTPException(400, detail={"success": False, "error": "Nombre requerido"})

    user_id = int(user["sub"])
    try:
        group = InventoryGroupService.create_group(
            db,
            {
                "name": body["name"],
                "department_id": campaign.department_id,
                "group_type": body.get("group_type", "CLASSROOM"),
                "description": body.get("description"),
                "building": body.get("building"),
                "floor": body.get("floor"),
                "location_notes": body.get("location_notes"),
            },
            created_by_id=user_id,
        )
        return {"success": True, "message": f"Grupo {group.name} creado", "data": group.to_dict()}
    except ValueError as e:
        raise HTTPException(400, detail={"success": False, "error": str(e)})
    except Exception as e:
        db.rollback()
        logger.error("create_group_in_campaign %d: %s", campaign_id, e, exc_info=True)
        raise HTTPException(500, detail={"success": False, "error": "Error interno al crear el grupo"})


# ── POST /{id}/groups/{group_id}/items/{item_id} — Asignar item a grupo ────────

@router.post("/{campaign_id}/groups/{group_id}/items/{item_id}")
def assign_item_to_group(
    campaign_id: int,
    group_id: int,
    item_id: int,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.campaign.api.manage"]),
    db: DbSession = None,
):
    """
    Asigna un item al grupo dentro del contexto de la campaña.
    Solo permitido en campañas OPEN. El item debe pertenecer al depto.
    """
    from itcj2.apps.helpdesk.models.inventory_group import InventoryGroup
    from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
    from itcj2.apps.helpdesk.services.inventory_history_service import InventoryHistoryService

    campaign = _get_campaign_or_404(db, campaign_id)
    if not campaign.is_open:
        raise HTTPException(400, detail={
            "success": False,
            "error": "Solo se pueden mover items en campañas OPEN",
        })

    group = db.get(InventoryGroup, group_id)
    if not group or group.department_id != campaign.department_id:
        raise HTTPException(404, detail={"success": False, "error": "Grupo no encontrado en el depto"})

    item = db.get(InventoryItem, item_id)
    if not item or not item.is_active:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no encontrado"})
    if item.department_id != campaign.department_id:
        raise HTTPException(400, detail={"success": False, "error": "El equipo no pertenece al depto"})

    old_group_id = item.group_id
    item.group_id = group_id
    InventoryHistoryService.log_event(
        db=db,
        item_id=item_id,
        event_type="GROUP_ASSIGNED",
        performed_by_id=int(user["sub"]),
        old_value={"group_id": old_group_id},
        new_value={"group_id": group_id, "campaign_id": campaign_id},
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(item)
    return {"success": True, "message": f"Equipo movido al grupo {group.name}", "data": item.to_dict()}


# ── DELETE /{id}/groups/{group_id}/items/{item_id} — Quitar item de grupo ──────

@router.delete("/{campaign_id}/groups/{group_id}/items/{item_id}")
def remove_item_from_group(
    campaign_id: int,
    group_id: int,
    item_id: int,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.campaign.api.manage"]),
    db: DbSession = None,
):
    """Quita un item del grupo (lo deja sin grupo) durante la campaña OPEN."""
    from itcj2.apps.helpdesk.models.inventory_item import InventoryItem
    from itcj2.apps.helpdesk.services.inventory_history_service import InventoryHistoryService

    campaign = _get_campaign_or_404(db, campaign_id)
    if not campaign.is_open:
        raise HTTPException(400, detail={
            "success": False,
            "error": "Solo se pueden mover items en campañas OPEN",
        })

    item = db.get(InventoryItem, item_id)
    if not item or item.group_id != group_id:
        raise HTTPException(404, detail={"success": False, "error": "Equipo no pertenece a ese grupo"})

    item.group_id = None
    InventoryHistoryService.log_event(
        db=db,
        item_id=item_id,
        event_type="GROUP_UNASSIGNED",
        performed_by_id=int(user["sub"]),
        old_value={"group_id": group_id},
        new_value={"group_id": None, "campaign_id": campaign_id},
        ip_address=_client_ip(request),
    )
    db.commit()
    return {"success": True, "message": "Equipo removido del grupo"}


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
