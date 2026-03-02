"""
Ticket Collaborators API v2 — 8 endpoints.
Fuente: itcj/apps/helpdesk/routes/api/tickets/collaborators.py
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from itcj2.dependencies import DbSession, require_perms
from itcj2.apps.helpdesk.schemas.tickets import (
    AddCollaboratorRequest,
    AddCollaboratorsBatchRequest,
    UpdateCollaboratorRequest,
)

router = APIRouter(tags=["helpdesk-collaborators"])
logger = logging.getLogger(__name__)


@router.post("/{ticket_id}/collaborators", status_code=201)
def add_collaborator(
    ticket_id: int,
    body: AddCollaboratorRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.resolve"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import collaborator_service

    user_id = int(user["sub"])

    if not collaborator_service.can_user_manage_collaborators(user_id, ticket_id):
        raise HTTPException(403, detail={"error": "forbidden", "message": "No tienes permiso para gestionar colaboradores de este ticket"})

    collaborator = collaborator_service.add_collaborator(
        db,
        ticket_id=ticket_id,
        user_id=body.user_id,
        collaboration_role=body.collaboration_role,
        time_invested_minutes=body.time_invested_minutes,
        notes=body.notes,
        added_by_id=user_id,
    )

    logger.info(f"Colaborador {body.user_id} agregado al ticket {ticket_id}")
    return {"message": "Colaborador agregado exitosamente", "collaborator": collaborator.to_dict()}


@router.post("/{ticket_id}/collaborators/batch", status_code=201)
def add_multiple_collaborators(
    ticket_id: int,
    body: AddCollaboratorsBatchRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.resolve"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import collaborator_service

    user_id = int(user["sub"])

    if not body.collaborators:
        raise HTTPException(400, detail={"error": "empty_collaborators", "message": "La lista de colaboradores está vacía"})

    if not collaborator_service.can_user_manage_collaborators(user_id, ticket_id):
        raise HTTPException(403, detail={"error": "forbidden", "message": "No tienes permiso para gestionar colaboradores de este ticket"})

    collaborators_data = [c.model_dump() for c in body.collaborators]
    collaborators = collaborator_service.add_multiple_collaborators(
        db,
        ticket_id=ticket_id,
        collaborators_data=collaborators_data,
        added_by_id=user_id,
    )

    logger.info(f"{len(collaborators)} colaboradores agregados al ticket {ticket_id}")
    return {
        "message": f"{len(collaborators)} colaboradores agregados exitosamente",
        "collaborators": [c.to_dict() for c in collaborators],
        "count": len(collaborators),
    }


@router.get("/{ticket_id}/collaborators")
def get_collaborators(
    ticket_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import collaborator_service
    from itcj2.apps.helpdesk.services.ticket_service import get_ticket_by_id

    user_id = int(user["sub"])
    get_ticket_by_id(db, ticket_id, user_id, check_permissions=True)

    collaborators = collaborator_service.get_ticket_collaborators(ticket_id)
    return {
        "ticket_id": ticket_id,
        "collaborators": [c.to_dict() for c in collaborators],
        "count": len(collaborators),
    }


@router.put("/{ticket_id}/collaborators/{collab_user_id}")
def update_collaborator(
    ticket_id: int,
    collab_user_id: int,
    body: UpdateCollaboratorRequest,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.resolve"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import collaborator_service

    user_id = int(user["sub"])

    if body.time_invested_minutes is None and body.notes is None:
        raise HTTPException(400, detail={"error": "missing_fields", "message": "Debe proporcionar al menos time_invested_minutes o notes"})

    if not collaborator_service.can_user_manage_collaborators(user_id, ticket_id):
        raise HTTPException(403, detail={"error": "forbidden", "message": "No tienes permiso para modificar colaboradores de este ticket"})

    collaborator = collaborator_service.update_collaborator(
        db,
        ticket_id=ticket_id,
        user_id=collab_user_id,
        time_invested_minutes=body.time_invested_minutes,
        notes=body.notes,
    )

    logger.info(f"Colaborador {collab_user_id} actualizado en ticket {ticket_id}")
    return {"message": "Colaborador actualizado exitosamente", "collaborator": collaborator.to_dict()}


@router.delete("/{ticket_id}/collaborators/{collab_user_id}")
def remove_collaborator(
    ticket_id: int,
    collab_user_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.resolve"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import collaborator_service

    user_id = int(user["sub"])

    if not collaborator_service.can_user_manage_collaborators(user_id, ticket_id):
        raise HTTPException(403, detail={"error": "forbidden", "message": "No tienes permiso para remover colaboradores de este ticket"})

    collaborator_service.remove_collaborator(db, ticket_id=ticket_id, user_id=collab_user_id)

    logger.info(f"Colaborador {collab_user_id} removido del ticket {ticket_id}")
    return {"message": "Colaborador removido exitosamente"}


@router.get("/{ticket_id}/collaborators/suggest-role/{collab_user_id}")
def suggest_role(
    ticket_id: int,
    collab_user_id: int,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.resolve"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import collaborator_service

    suggested_role = collaborator_service.suggest_collaboration_role(
        user_id=collab_user_id, ticket_id=ticket_id
    )
    return {"ticket_id": ticket_id, "user_id": collab_user_id, "suggested_role": suggested_role}


@router.get("/collaborations/me")
def my_collaborations(
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import collaborator_service

    user_id = int(user["sub"])
    params = request.query_params
    page = int(params.get("page", "1"))
    per_page = min(int(params.get("per_page", "20")), 100)

    result = collaborator_service.get_tickets_where_user_collaborated(
        user_id=user_id, page=page, per_page=per_page
    )
    return result


@router.get("/collaborations/me/stats")
def my_collaboration_stats(
    request: Request,
    user: dict = require_perms("helpdesk", ["helpdesk.tickets.api.read.own"]),
    db: DbSession = None,
):
    from itcj2.apps.helpdesk.services import collaborator_service

    user_id = int(user["sub"])
    days = min(int(request.query_params.get("days", "30")), 365)

    stats = collaborator_service.get_user_collaboration_stats(user_id=user_id, days=days)
    return stats
