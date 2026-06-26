"""
Department Head API — Endpoints para el dashboard del jefe de departamento.

Rutas (prefix: /api/help-desk/v2/department-head):
  GET  /pending-tasks                              → Tareas pendientes agrupadas por categoría
  GET  /secretaries                                → Lista de secretarias del departamento del caller
  POST /secretaries/{secretary_id}/reset-password  → Resetea contraseña de una secretaria
"""
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request

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
    user: dict = require_perms("helpdesk", [
        "helpdesk.dashboard.department",
        "helpdesk.inventory.retirement.api.read",
        "helpdesk.inventory.campaign.api.read",
    ]),
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
                "url":           f"/help-desk/inventory/campaigns/{c.id}/validate",
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
            "AWAITING_SUBDIRECTOR":         "subdirector_admin_services",
            "AWAITING_DIRECTOR":            "director",
            "AWAITING_COMP_CENTER":         "head_comp_center",
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


def _get_department_code(db, user_id: int):
    """
    Retorna (dept_id, dept_code) del puesto activo del usuario.
    Si no tiene puesto activo, retorna (None, None).
    """
    from itcj2.core.models.position import UserPosition, Position
    from itcj2.core.models.department import Department

    row = (
        db.query(Position.department_id, Department.code)
        .join(UserPosition, UserPosition.position_id == Position.id)
        .join(Department, Department.id == Position.department_id)
        .filter(
            UserPosition.user_id == user_id,
            UserPosition.is_active == True,
            Position.is_active == True,
            Department.is_active == True,
        )
        .first()
    )
    return (row[0], row[1]) if row else (None, None)


def _is_head_of_dept(db, user_id: int, dept_code: str) -> bool:
    """
    Verifica que el usuario tenga un puesto activo con code = 'head_{dept_code}'
    en ese departamento.
    """
    from itcj2.core.models.position import UserPosition, Position
    from itcj2.core.models.department import Department

    row = (
        db.query(Position.id)
        .join(UserPosition, UserPosition.position_id == Position.id)
        .join(Department, Department.id == Position.department_id)
        .filter(
            UserPosition.user_id == user_id,
            UserPosition.is_active == True,
            Position.is_active == True,
            Position.code == f"head_{dept_code}",
            Department.code == dept_code,
            Department.is_active == True,
        )
        .first()
    )
    return row is not None


@router.get("/secretaries")
def list_secretaries(
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.department.api.reset_secretary_password"]),
    db: DbSession = None,
):
    """
    Lista las secretarias activas del departamento del jefe autenticado.
    """
    user_id = int(user["sub"])

    dept_id, dept_code = _get_department_code(db, user_id)
    if dept_code is None:
        raise HTTPException(status_code=403, detail="No tienes departamento asignado")

    try:
        from itcj2.core.models.position import UserPosition, Position
        from itcj2.core.models.user import User

        secretaries = (
            db.query(User)
            .join(UserPosition, UserPosition.user_id == User.id)
            .join(Position, Position.id == UserPosition.position_id)
            .filter(
                UserPosition.is_active == True,
                Position.is_active == True,
                Position.code == f"secretary_{dept_code}",
                Position.department_id == dept_id,
                User.is_active == True,
            )
            .all()
        )

        data = [
            {
                "id":                   s.id,
                "full_name":            s.full_name,
                "username":             s.username,
                "email":                s.email,
                "must_change_password": s.must_change_password,
            }
            for s in secretaries
        ]
        return {"success": True, "data": data, "total": len(data)}

    except Exception as e:
        logger.error(f"[secretaries] Error listando secretarias para user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno al listar secretarias")


@router.post("/secretaries/{secretary_id}/reset-password")
def reset_secretary_password(
    secretary_id: int,
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.department.api.reset_secretary_password"]),
    db: DbSession = None,
):
    """
    Resetea la contraseña de una secretaria del mismo departamento del jefe autenticado.
    La nueva contraseña es 'tecno#2K' y se fuerza el cambio en el próximo login.
    """
    user_id = int(user["sub"])

    try:
        dept_id, dept_code = _get_department_code(db, user_id)
        if dept_code is None:
            raise HTTPException(status_code=403, detail="No tienes departamento asignado")

        if not _is_head_of_dept(db, user_id, dept_code):
            raise HTTPException(status_code=403, detail="No eres jefe del departamento")

        from itcj2.core.models.user import User
        from itcj2.core.models.position import UserPosition, Position
        from itcj2.core.utils.security import hash_nip

        target = db.get(User, secretary_id)
        if not target:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        # Verificar que el target sea secretaria del mismo departamento
        secretary_position = (
            db.query(Position.id)
            .join(UserPosition, UserPosition.position_id == Position.id)
            .filter(
                UserPosition.user_id == secretary_id,
                UserPosition.is_active == True,
                Position.is_active == True,
                Position.code == f"secretary_{dept_code}",
                Position.department_id == dept_id,
            )
            .first()
        )
        if not secretary_position:
            raise HTTPException(
                status_code=403,
                detail="El usuario no es secretaria de tu departamento",
            )

        target.password_hash = hash_nip("tecno#2K")
        target.must_change_password = True
        db.commit()

        logger.info(
            f"[reset-password] User {user_id} reseteó contraseña de secretaria {secretary_id} "
            f"(dept: {dept_code})"
        )

        return {
            "success": True,
            "message": "Contraseña reseteada correctamente",
            "data": {
                "user_id":             secretary_id,
                "must_change_password": True,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"[reset-password] Error al resetear contraseña de {secretary_id} por user {user_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Error interno al resetear contraseña")


@router.post("/reset-my-password")
def reset_my_password(
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.department.api.reset_secretary_password"]),
    db: DbSession = None,
):
    """
    El jefe restablece su PROPIA contraseña a la temporal 'tecno#2K'.
    No permite elegir una contraseña arbitraria: siempre queda en la temporal
    y se fuerza el cambio en el próximo inicio de sesión.
    """
    user_id = int(user["sub"])
    try:
        from itcj2.core.models.user import User
        from itcj2.core.utils.security import hash_nip

        target = db.get(User, user_id)
        if not target:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        target.password_hash = hash_nip("tecno#2K")
        target.must_change_password = True
        db.commit()

        logger.info(f"[reset-my-password] User {user_id} restableció su propia contraseña a la temporal")

        return {
            "success": True,
            "message": "Tu contraseña se restableció a la temporal (tecno#2K)",
            "data": {
                "user_id":             user_id,
                "must_change_password": True,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[reset-my-password] Error para user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno al restablecer contraseña")
