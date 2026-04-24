"""
Department Head API — Endpoints para el dashboard del jefe de departamento.

Rutas (prefix: /api/help-desk/v2/department-head):
  GET /pending-tasks  → Tareas pendientes agrupadas por categoría
"""
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException

from itcj2.dependencies import DbSession, require_perms

router = APIRouter(tags=["helpdesk-department-head"])
logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_user_department_id(db, user_id: int):
    """
    Retorna el department_id del puesto activo del usuario, o None si no tiene puesto.
    """
    from itcj2.core.models.position import UserPosition, Position

    row = (
        db.query(Position.department_id)
        .join(UserPosition, UserPosition.position_id == Position.id)
        .filter(
            UserPosition.user_id == user_id,
            UserPosition.is_active == True,
            Position.is_active == True,
        )
        .first()
    )
    return row[0] if row else None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/pending-tasks")
def get_pending_tasks(
    user: dict = require_perms("helpdesk", ["helpdesk.inventory.retirement.api.read"]),
    db: DbSession = None,
):
    """
    Retorna las tareas pendientes del jefe de departamento autenticado,
    agrupadas en tres categorías:
      - campaigns:          Campañas de inventario pendientes de validación
      - pending_retirements: Solicitudes de baja esperando la firma del usuario
      - unrated_tickets:    Tickets del departamento sin calificar (últimos 30 días)
    """
    user_id = int(user["sub"])

    # ── Categoría 1: Campañas pendientes de validación ─────────────────────────
    campaigns = []
    try:
        from itcj2.apps.helpdesk.models.inventory_campaign import InventoryCampaign

        department_id = _get_user_department_id(db, user_id)

        query = db.query(InventoryCampaign).filter(
            InventoryCampaign.status == "PENDING_VALIDATION"
        )
        if department_id is not None:
            query = query.filter(InventoryCampaign.department_id == department_id)
        # TODO: filtrar por departamento cuando department_id sea None (sin puesto activo)

        for c in query.order_by(InventoryCampaign.closed_at.asc()).all():
            campaigns.append({
                "id":            c.id,
                "folio":         c.folio,
                "title":         c.title,
                "status":        c.status,
                "pending_count": c.items_count,
                "url":           f"/help-desk/inventory/campaigns/{c.id}",
            })
    except Exception as e:
        logger.error(f"[pending-tasks] Error consultando campañas para user {user_id}: {e}", exc_info=True)

    # ── Categoría 2: Solicitudes de baja esperando firma ───────────────────────
    pending_retirements = []
    try:
        from itcj2.apps.helpdesk.models.inventory_retirement_request import (
            InventoryRetirementRequest,
            InventoryRetirementSignature,
        )
        from itcj2.core.services.authz_service import _get_users_with_position

        # Mapeo: status de la solicitud → position_code que debe firmar
        STATUS_TO_POSITION = {
            "AWAITING_RECURSOS_MATERIALES": "head_mat_services",
            "AWAITING_SUBDIRECTOR":         "secretary_sub_admin_services",
            "AWAITING_DIRECTOR":            "director",
        }

        # Determinar en qué statuses tiene competencia el usuario
        eligible_statuses = []
        for status, position_code in STATUS_TO_POSITION.items():
            users_with_position = _get_users_with_position(db, [position_code])
            if user_id in users_with_position:
                eligible_statuses.append(status)

        if eligible_statuses:
            # Solicitudes en los statuses donde el usuario tiene firma
            solicitudes = (
                db.query(InventoryRetirementRequest)
                .filter(InventoryRetirementRequest.status.in_(eligible_statuses))
                .order_by(InventoryRetirementRequest.created_at.asc())
                .all()
            )

            # Excluir las que ya tiene una firma del usuario en esa etapa
            already_signed_ids = set(
                row[0]
                for row in db.query(InventoryRetirementSignature.request_id)
                .filter(
                    InventoryRetirementSignature.signed_by_id == user_id,
                    InventoryRetirementSignature.action.isnot(None),
                )
                .all()
            )

            for req in solicitudes:
                if req.id in already_signed_ids:
                    continue
                requested_by_name = (
                    req.requested_by.full_name if req.requested_by else None
                )
                pending_retirements.append({
                    "id":                req.id,
                    "folio":             req.folio,
                    "status":            req.status,
                    "reason":            req.reason,
                    "requested_by_name": requested_by_name,
                    "created_at":        req.created_at.isoformat() if req.created_at else None,
                    "url":               f"/help-desk/inventory/retirement-requests/{req.id}",
                })
    except Exception as e:
        logger.error(f"[pending-tasks] Error consultando bajas para user {user_id}: {e}", exc_info=True)

    # ── Categoría 3: Tickets del departamento sin calificar ────────────────────
    unrated_tickets = {"count": 0, "url": "/help-desk/tickets?filter=unrated"}
    try:
        from itcj2.apps.helpdesk.models.ticket import Ticket

        department_id = _get_user_department_id(db, user_id)
        cutoff = datetime.utcnow() - timedelta(days=30)

        count_query = db.query(Ticket).filter(
            Ticket.status.in_(["RESOLVED_SUCCESS", "RESOLVED_FAILED"]),
            Ticket.rating_attention.is_(None),
            Ticket.resolved_at >= cutoff,
        )

        if department_id is not None:
            count_query = count_query.filter(
                Ticket.requester_department_id == department_id
            )
        # TODO: filtrar por departamento cuando department_id sea None (sin puesto activo)

        unrated_tickets["count"] = count_query.count()
    except Exception as e:
        logger.error(f"[pending-tasks] Error consultando tickets sin calificar para user {user_id}: {e}", exc_info=True)

    return {
        "success": True,
        "data": {
            "campaigns":          campaigns,
            "pending_retirements": pending_retirements,
            "unrated_tickets":    unrated_tickets,
        },
    }
